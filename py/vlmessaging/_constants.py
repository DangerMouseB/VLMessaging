# **********************************************************************************************************************
# Copyright 2025 David Briant, https://github.com/coppertop-bones. Licensed under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance with the License. You may obtain a copy of the  License at
# http://www.apache.org/licenses/LICENSE-2.0. Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY  KIND,
# either express or implied. See the License for the specific language governing permissions and limitations under the
# License. See the NOTICE file distributed with this work for additional information regarding copyright ownership.
# **********************************************************************************************************************


LOCAL = None

PUB = None
PROCESS_WIDE = 'PROCESS_WIDE'
MACHINE_WIDE = 'MACHINE_WIDE'
NETWORK = 'NETWORK'


DIRECTORY_CHECK_INTERVAL = 5000  # seconds

REGISTER_ENTRY = 'REGISTER_ENTRY'
UNREGISTER_ENTRY = 'UNREGISTER_ENTRY'
UNREGISTER_ADDR = 'UNREGISTER_ADDR'
GET_ENTRIES = 'GET_ENTRIES'

HEARTBEAT = 'HEARTBEAT'

GET_AGENT_ID = 'GET_AGENT_ID'
CLOSING_AGENT = 'CLOSING_AGENT'

DOES_NOT_UNDERSTAND = 'DOES_NOT_UNDERSTAND'
MSG_NOT_DELIVERED = 'MSG_NOT_DELIVERED'
IGNORE_UNHANDLED_REPLIES = 'IGNORE_UNHANDLED_REPLIES'
HANDLE_DOES_NOT_UNDERSTAND = 'HANDLE_DOES_NOT_UNDERSTAND'
