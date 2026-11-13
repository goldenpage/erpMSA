#!/usr/bin/env python3
"""Create a new manual disposal retry Job, run it once, and fetch its JSON."""

import argparse
import base64
import ipaddress
import json
import os
from pathlib import Path
import re
import stat
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "jenkins/disposal-concurrent-retries-job.xml"
JOB_PREFIX = "disposal-concurrent-retries"
NODE_LABEL = "erpmsa-disposal-live"
ARTIFACT = "artifacts/disposal-concurrent-retries.json"
SCENARIOS = ("before-deduction", "lost-stock-response")
MAX_RESPONSE = 2 * 1024 * 1024


class RunError(Exception):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


def validated_url(value):
    parsed = urlsplit(value.rstrip("/"))
    loopback = False
    if parsed.hostname:
        try:
            loopback = ipaddress.ip_address(parsed.hostname).is_loopback
        except ValueError:
            pass
    if (not parsed.hostname or parsed.username is not None or parsed.query or parsed.fragment
            or (parsed.scheme != "https" and not (parsed.scheme == "http" and loopback))):
        raise RunError("Jenkins HTTPS 주소를 사용하세요. HTTP는 루프백 IP에서만 허용됩니다.")
    return parsed.geturl()


def auth_header(path):
    metadata = path.stat()
    if not stat.S_ISREG(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) & 0o077:
        raise RunError("인증 파일을 일반 파일로 만들고 권한을 600으로 제한하세요.")
    credential = path.read_text(encoding="utf-8").strip()
    user, separator, token = credential.partition(":")
    if not separator or not user or not token or any(character.isspace() for character in credential):
        raise RunError("인증 파일에는 username:api-token 한 줄이 필요합니다.")
    return "Basic " + base64.b64encode(credential.encode()).decode()


class Jenkins:
    def __init__(self, url, auth_file):
        self.url = validated_url(url)
        self.authorization = auth_header(auth_file)
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    def request(self, path, *, data=None, content_type=None, allow_missing=False):
        headers = {"Authorization": self.authorization}
        if content_type:
            headers["Content-Type"] = content_type
        try:
            with self.opener.open(Request(self.url + path, data=data, headers=headers), timeout=15) as response:
                raw = response.read(MAX_RESPONSE + 1)
                if len(raw) > MAX_RESPONSE:
                    raise RunError(f"Jenkins 응답 한도 초과 | {path}")
                return response.status, response.headers, raw
        except HTTPError as error:
            if allow_missing and error.code == 404:
                return None
            raise RunError(f"Jenkins HTTP {error.code} | {path}") from error
        except (URLError, TimeoutError) as error:
            hint = " | Jenkins에서 요청 처리 여부를 먼저 확인하세요." if data is not None else ""
            raise RunError(f"Jenkins 연결 실패 | {path}{hint}") from error

    def json(self, path, *, allow_missing=False):
        response = self.request(path, allow_missing=allow_missing)
        if response is None:
            return None
        result = json.loads(response[2])
        if not isinstance(result, dict):
            raise RunError(f"Jenkins JSON 객체가 필요합니다 | {path}")
        return result

    def queue_path(self, location):
        if not location:
            raise RunError("빌드 큐 Location이 없습니다. Jenkins에서 실행 여부를 확인하세요.")
        target = urlsplit(urljoin(self.url + "/", location))
        base = urlsplit(self.url)
        prefix = base.path + "/queue/item/"
        if ((target.scheme, target.netloc) != (base.scheme, base.netloc)
                or target.query or target.fragment or not target.path.startswith(prefix)
                or not re.fullmatch(r"[0-9]+/?", target.path.removeprefix(prefix))):
            raise RunError("Jenkins 빌드 큐 주소가 예상 범위를 벗어났습니다.")
        return target.path.removeprefix(base.path).rstrip("/")


def preflight(client, job_path):
    if client.json(job_path + "/api/json", allow_missing=True) is not None:
        raise RunError("같은 이름의 Job이 있습니다. 새 전용 이름을 지정하세요.")
    controller = client.json("/api/json?tree=quietingDown")
    if controller.get("quietingDown"):
        raise RunError("Jenkins가 새 빌드를 받지 않는 상태입니다.")

    query = urlencode({"tree": "computer[displayName,offline,temporarilyOffline,numExecutors,assignedLabels[name]]"})
    computers = client.json("/computer/api/json?" + query)["computer"]
    nodes = [node for node in computers if any(label["name"] == NODE_LABEL for label in node["assignedLabels"])]
    if len(nodes) != 1:
        raise RunError(f"{NODE_LABEL} 라벨을 가진 노드가 정확히 하나 필요합니다. 현재 {len(nodes)}개입니다.")
    node = nodes[0]
    if node["offline"] or node.get("temporarilyOffline") or node["numExecutors"] < 1:
        raise RunError(f"실행 노드가 오프라인이거나 실행기가 없습니다 | {node['displayName']}")
    print(f"노드 확인 | {node['displayName']} | {NODE_LABEL} | 실행기 {node['numExecutors']}개", flush=True)
    return "" if node.get("_class", "").endswith("$MasterComputer") else node["displayName"]


def wait_for(probe, seconds, description):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        result = probe()
        if result is not None:
            return result
        time.sleep(2)
    raise RunError(f"{description} 대기 시간 초과. Jenkins에서 해당 실행 상태를 확인하세요.")


def run_once(client, job_name, job_path, timeout):
    status, _, _ = client.request("/createItem?" + urlencode({"name": job_name}), data=TEMPLATE.read_bytes(),
                                  content_type="application/xml")
    if status not in (200, 201):
        raise RunError(f"새 Job 등록 상태를 확인하세요 | HTTP {status}")
    job = client.json(job_path + "/api/json?tree=name,nextBuildNumber")
    if (job.get("_class") != "hudson.model.FreeStyleProject"
            or job.get("name") != job_name or job.get("nextBuildNumber") != 1):
        raise RunError("새로 등록된 수동 Freestyle Job을 확인하지 못했습니다.")
    print(f"새 Job 등록 | {client.url}{job_path}/", flush=True)
    status, headers, _ = client.request(job_path + "/build?delay=0sec", data=b"",
                                        content_type="application/x-www-form-urlencoded")
    if status != 201:
        raise RunError(f"Jenkins 빌드 큐 등록 상태를 확인하세요 | HTTP {status}")
    queue = client.queue_path(headers.get("Location"))
    print(f"수동 빌드 요청 | {client.url}{queue}/", flush=True)

    def queued_build():
        data = client.json(queue + "/api/json")
        if data.get("cancelled"):
            raise RunError("Jenkins에서 빌드가 취소됐습니다.")
        if data.get("task", {}).get("name") != job_name:
            raise RunError("큐에 등록된 Job 이름이 일치하지 않습니다.")
        return data.get("executable")

    executable = wait_for(queued_build, timeout, "빌드 시작")
    number = executable["number"]
    if type(number) is not int or number != 1:
        raise RunError("새 Job의 첫 빌드 번호와 일치하지 않습니다. Jenkins에서 큐를 확인하세요.")
    build_path = f"{job_path}/{number}"
    print(f"빌드 #{number} | {client.url}{build_path}/", flush=True)

    def completed_build():
        data = client.json(build_path + "/api/json?tree=number,building,result,builtOn,artifacts[relativePath]")
        if not data["building"] and data.get("result"):
            return data
        return None

    return build_path, wait_for(completed_build, timeout, "빌드 완료")


def report_passed(report):
    cases = report.get("scenarios")
    return (report.get("status") == "PASS" and report.get("backupUnchanged") is True
            and isinstance(cases, list) and all(isinstance(case, dict) for case in cases)
            and [case.get("scenario") for case in cases] == list(SCENARIOS)
            and all(case.get("status") == "PASS" and case.get("agentDbReadOnly") is True
                    and case.get("temporaryRuntimeRemoved") is True and len(case.get("a2aCompleted", [])) == 2
                    for case in cases))


def download_report(client, build_path, build, output):
    if ARTIFACT not in {artifact["relativePath"] for artifact in build["artifacts"]}:
        raise RunError(f"빌드 {build['result']} | 결과 JSON 없음 | {client.url}{build_path}/console")
    _, _, payload = client.request(build_path + "/artifact/" + ARTIFACT)
    report = json.loads(payload)
    if not isinstance(report, dict):
        raise RunError("다운로드한 아티팩트가 결과 JSON 객체가 아닙니다.")
    descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(payload)
    print(f"아티팩트 저장 | {output.resolve()}", flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, help="허용된 IP에서 접근할 Jenkins 기본 URL")
    parser.add_argument("--auth-file", required=True, type=Path, help="권한 600의 username:api-token 파일")
    parser.add_argument("--job-name", default=JOB_PREFIX, help=f"새 {JOB_PREFIX} 또는 {JOB_PREFIX}-접미사")
    parser.add_argument("--output", type=Path, help="다운로드할 새 JSON 파일 경로")
    parser.add_argument("--timeout", type=int, default=900, help="큐와 빌드 각각의 최대 대기 초")
    parser.add_argument("--check-only", action="store_true", help="Job 이름과 노드 상태만 읽기 전용 확인")
    args = parser.parse_args()
    if not re.fullmatch(JOB_PREFIX + r"(?:-[A-Za-z0-9][A-Za-z0-9_-]{0,63})?", args.job_name):
        parser.error(f"--job-name은 {JOB_PREFIX} 전용 이름을 사용하세요.")
    if args.timeout < 1:
        parser.error("--timeout은 양의 초 단위 값이어야 합니다.")
    if not args.check_only and (args.output is None or not args.output.parent.is_dir()
                                or args.output.exists() or args.output.is_symlink()):
        parser.error("--output은 기존 디렉터리의 새 JSON 파일 경로여야 합니다.")

    try:
        client = Jenkins(args.url, args.auth_file)
        job_path = "/job/" + quote(args.job_name, safe="")
        node = preflight(client, job_path)
        if args.check_only:
            print("사전 확인 완료 | 새 Job 등록 가능")
            return 0
        build_path, build = run_once(client, args.job_name, job_path, args.timeout)
        report = download_report(client, build_path, build, args.output)
        if build.get("builtOn") != node:
            raise RunError("빌드가 사전에 확인한 노드에서 실행되지 않았습니다.")
        if build["result"] != "SUCCESS" or not report_passed(report):
            raise RunError(f"통합 검증 실패 | Jenkins {build['result']} | {client.url}{build_path}/")
        print("검증 완료 | 두 시나리오와 조회 전용 A2A 통과")
        return 0
    except (RunError, OSError, ValueError, KeyError, TypeError) as error:
        print(f"Jenkins 검증 실패 | {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
