# **********************************************************************************************************************
# Copyright 2025 David Briant, https://github.com/coppertop-bones. Licensed under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance with the License. You may obtain a copy of the  License at
# http://www.apache.org/licenses/LICENSE-2.0. Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY  KIND,
# either express or implied. See the License for the specific language governing permissions and limitations under the
# License. See the NOTICE file distributed with this work for additional information regarding copyright ownership.
# **********************************************************************************************************************

# Directory utilities

# Python imports
import asyncio

# local imports
from vlmessaging._utils.sentinels import Missing
from vlmessaging._utils.utils import Timer
from vlmessaging import _constants as VLM
from vlmessaging._core import ExitMessageHandler, Msg


# work-in-progress utils

async def _waitForSingleEntryAddrOfTypeOrReplyAndExit(connection, entryType, totalTimeout, msgTimeout, errMsg):
    t = Timer(totalTimeout)
    while not t:
        if entry := await _findSingleEntryAddrOfTypeOrMissing(connection, entryType, msgTimeout, errMsg): return entry
        await asyncio.sleep(msgTimeout)
    await _replyAndExit(connection, errMsg)

async def _findSingleEntryAddrOfTypeOrReplyAndExit(connection, entryType, timeout, errMsg):
    if entry := await _findSingleEntryAddrOfTypeOrMissing(connection, entryType, timeout, errMsg): return entry
    await _replyAndExit(connection, errMsg)

async def _findSingleEntryAddrOfTypeOrMissing(connection, entryType, timeout, errMsg):
    for entry in await _findEntriesOfTypeOrExit(connection, entryType, timeout, errMsg):
        if entry.service == entryType: return entry.addr
    return Missing

async def _findEntriesOfTypeOrExit(connection, entryType, timeout, errMsg):
    res = await connection.send(Msg(connection.directoryAddr, VLM.GET_ENTRIES, entryType), timeout)
    if res is Missing: await _replyAndExit(connection, errMsg)
    return res.contents

async def _replyAndExit(connection, errMsg):
    if errMsg: await connection.send(errMsg)
    raise ExitMessageHandler()
