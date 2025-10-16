# **********************************************************************************************************************
# Copyright 2025 David Briant, https://github.com/coppertop-bones. Licensed under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance with the License. You may obtain a copy of the  License at
# http://www.apache.org/licenses/LICENSE-2.0. Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY  KIND,
# either express or implied. See the License for the specific language governing permissions and limitations under the
# License. See the NOTICE file distributed with this work for additional information regarding copyright ownership.
# **********************************************************************************************************************

# local imports
from vlmessaging._structs import Addr


PUB = None
LOCAL = None
MACHINE = 'MACHINE'
NETWORKED = 'NETWORKED'

DIRECTORY_ADDR = "ipc:///tmp/directory"
DIRECTORY_CONNECTION_ID = 1
_AGENT_ADDR_PREFIX = "ipc:///tmp/agent"
DIRECTORY_CHECK_INTERVAL = 5000  # seconds

DIRECTORY = Addr(LOCAL, DIRECTORY_CONNECTION_ID)

addr = "tcp://127.0.0.1:13134"

REGISTER_ENTRY = 'REGISTER_ENTRY'
REGISTER_ENTRY_REPLY = 'REGISTER_ENTRY_REPLY'
UNREGISTER_ENTRY = 'UNREGISTER_ENTRY'
UNREGISTER_ENTRY_REPLY = 'UNREGISTER_ENTRY_REPLY'
UNREGISTER_ADDR = 'UNREGISTER_ADDR'
UNREGISTER_ADDR_REPLY = 'UNREGISTER_ADDR_REPLY'
GET_ENTRIES = 'GET_ENTRIES'
GET_ENTRIES_REPLY = 'GET_ENTRIES_REPLY'

HEARTBEAT = 'HEARTBEAT'
HEARTBEAT_REPLY = 'HEARTBEAT_REPLY'

GET_AGENT_ID = 'GET_AGENT_ID'
GET_AGENT_ID_REPLY = 'GET_AGENT_ID_REPLY'
CLOSING_AGENT = 'CLOSING_AGENT'

DOES_NOT_UNDERSTAND = 'DOES_NOT_UNDERSTAND'
MSG_NOT_DELIVERED = 'MSG_NOT_DELIVERED'
IGNORE_UNHANDLED_REPLIES = 'IGNORE_UNHANDLED_REPLIES'
HANDLE_DOES_NOT_UNDERSTAND = 'HANDLE_DOES_NOT_UNDERSTAND'
