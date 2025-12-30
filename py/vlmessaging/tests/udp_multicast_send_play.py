# see - https://stackoverflow.com/a/1794373

import socket

_GRP = '224.1.1.1'      # 224.0.0.0  to  239.255.255.255
_PORT = 30001

# for all packets sent, after two hops on the network the packet will not
# be re-sent/broadcast (see https://www.tldp.org/HOWTO/Multicast-HOWTO-6.html)
_TTL = 2

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, _TTL)

sock.sendto(b'robot', (_GRP, _PORT))

