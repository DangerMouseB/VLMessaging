# see - https://stackoverflow.com/a/1794373
import socket, struct

_GRP = '224.1.1.1'
_PORT = 30001

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.bind((_GRP, _PORT))
mreq = struct.pack('4sl', socket.inet_aton(_GRP), socket.INADDR_ANY)

sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)

while True:
  print(sock.recv(10240))



