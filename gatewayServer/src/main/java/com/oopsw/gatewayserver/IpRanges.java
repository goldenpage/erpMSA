package com.oopsw.gatewayserver;

import java.math.BigInteger;
import java.net.InetAddress;
import java.net.UnknownHostException;
import java.util.ArrayList;
import java.util.List;

/** 쉼표로 구분한 CIDR 목록(예: "10.0.0.0/8,::1/128")에 IP가 속하는지 검사한다. 호스트 이름은 받지 않는다. */
final class IpRanges {

    private record Range(byte[] network, int prefix) { }

    private final List<Range> ranges;

    private IpRanges(List<Range> ranges) {
        this.ranges = List.copyOf(ranges);
    }

    static IpRanges parse(String text) {
        List<Range> ranges = new ArrayList<>();
        if (text != null) {
            for (String part : text.split(",")) {
                String value = part.trim();
                if (value.isEmpty()) {
                    continue;
                }
                String[] pieces = value.split("/", 2);
                byte[] address = literal(pieces[0]);
                if (address == null) {
                    throw new IllegalArgumentException("Invalid CIDR: " + value);
                }
                int prefix = pieces.length == 2 ? Integer.parseInt(pieces[1]) : address.length * 8;
                if (prefix < 0 || prefix > address.length * 8) {
                    throw new IllegalArgumentException("Invalid CIDR prefix: " + value);
                }
                ranges.add(new Range(address, prefix));
            }
        }
        return new IpRanges(ranges);
    }

    boolean isEmpty() {
        return ranges.isEmpty();
    }

    boolean contains(String ip) {
        byte[] address = literal(ip);
        if (address == null) {
            return false;
        }
        for (Range range : ranges) {
            if (range.network().length == address.length && samePrefix(range.network(), address, range.prefix())) {
                return true;
            }
        }
        return false;
    }

    /** IP 리터럴만 허용한다. DNS 조회가 일어나지 않도록 문자 집합을 먼저 검사한다. */
    static byte[] literal(String value) {
        if (value == null || value.isBlank() || value.length() > 45 || !value.matches("[0-9A-Fa-f:.]+")) {
            return null;
        }
        if (!value.contains(":") && !value.matches("\\d{1,3}(\\.\\d{1,3}){3}")) {
            return null;
        }
        try {
            return InetAddress.getByName(value).getAddress();
        } catch (UnknownHostException exception) {
            return null;
        }
    }

    static String normalize(String value) {
        byte[] address = literal(value == null ? null : value.trim());
        if (address == null) {
            return null;
        }
        try {
            return InetAddress.getByAddress(address).getHostAddress();
        } catch (UnknownHostException exception) {
            return null;
        }
    }

    private static boolean samePrefix(byte[] network, byte[] address, int prefix) {
        int bits = network.length * 8;
        BigInteger mask = prefix == 0 ? BigInteger.ZERO
            : BigInteger.ONE.shiftLeft(prefix).subtract(BigInteger.ONE).shiftLeft(bits - prefix);
        return new BigInteger(1, network).and(mask).equals(new BigInteger(1, address).and(mask));
    }
}
