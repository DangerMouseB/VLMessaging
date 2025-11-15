# **********************************************************************************************************************
# Copyright 2025 David Briant, https://github.com/coppertop-bones. Licensed under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance with the License. You may obtain a copy of the  License at
# http://www.apache.org/licenses/LICENSE-2.0. Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY  KIND,
# either express or implied. See the License for the specific language governing permissions and limitations under the
# License. See the NOTICE file distributed with this work for additional information regarding copyright ownership.
# **********************************************************************************************************************

# how do we figure which ip / hostname to listen on in a multi-homed machine?

# see - https://stackoverflow.com/questions/166506/finding-local-ip-addresses-using-pythons-stdlib


# Python imports
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

