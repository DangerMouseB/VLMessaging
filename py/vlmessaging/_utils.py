# **********************************************************************************************************************
# Copyright 2025 David Briant, https://github.com/coppertop-bones. Licensed under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance with the License. You may obtain a copy of the  License at
# http://www.apache.org/licenses/LICENSE-2.0. Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY  KIND,
# either express or implied. See the License for the specific language governing permissions and limitations under the
# License. See the NOTICE file distributed with this work for additional information regarding copyright ownership.
# **********************************************************************************************************************


# 3rd party imports
from coppertop.utils import Missing

# local imports
from vlmessaging import _constants as VLM
from vlmessaging._core import ExitMessageHandler, Msg, Addr


# work-in-progress utils

async def _findEntriesOfTypeOrExit(connection, entryType, timeout, errMsg):
    res = await connection.send(Msg(connection.getDirectoryAddr(), VLM.GET_ENTRIES, entryType), timeout)
    if res is Missing:
        if errMsg: await connection.send(errMsg)
        raise ExitMessageHandler()
    else:
        return res.contents

async def _findSingleEntryAddrOfTypeOrExit(connection, entryType, timeout, errMsg):
    res = await connection.send(Msg(connection.getDirectoryAddr(), VLM.GET_ENTRIES, entryType), timeout)
    if res is Missing:
        if errMsg: await connection.send(errMsg)
        raise ExitMessageHandler()
    for entry in res.contents:
        if entry.service == entryType:
            return entry.addr
    if errMsg: await connection.send(errMsg)
    raise ExitMessageHandler()

