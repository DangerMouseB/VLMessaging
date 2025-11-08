
# see - https://stackoverflow.com/questions/166506/finding-local-ip-addresses-using-pythons-stdlib

import socket


print(hostname := socket.gethostname())


print(socket.gethostbyname(hostname))

print(socket.getfqdn())

# Very clever, works perfectly. Instead of gmail or 8.8.8.8, you can also use the IP or address of the server you want
# to be seen from, if that is applicable.
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.connect(('8.8.8.8', 1))   # connect() for UDP doesn't send packets
local_ip_address = s.getsockname()[0]


socket.gethostbyname_ex(socket.gethostname())

('davids-macbook-air.local', [], ['127.0.0.1', '10.147.17.16', '10.101.2.115'])

def getIpVia(host):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect((host, 1))
    return s.getsockname()

getIpVia('8.8.8.8')
 # ('10.101.2.115', 64424)

getIpVia('10.147.17.255')
('10.147.17.16', 60270)

