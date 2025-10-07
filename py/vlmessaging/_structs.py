# **********************************************************************************************************************
# Copyright 2025 David Briant, https://github.com/coppertop-bones. Licensed under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance with the License. You may obtain a copy of the  License at
# http://www.apache.org/licenses/LICENSE-2.0. Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY  KIND,
# either express or implied. See the License for the specific language governing permissions and limitations under the
# License. See the NOTICE file distributed with this work for additional information regarding copyright ownership.
# **********************************************************************************************************************

import collections


Addr = collections.namedtuple('Addr', ('socketAddr', 'connId'))

Entry = collections.namedtuple('Entry', ('addr', 'service', 'params'))


class Msg:
    __slots__ = ('fromAddr', 'toAddr', 'subject', '_msgId', '_replyId', 'contents', 'meta')
    def __init__(self, toAddr, subject, contents):
        self.fromAddr = None
        self.toAddr = toAddr
        self.subject = subject
        self._msgId = None
        self._replyId = None
        self.contents = contents
        self.meta = {}
    def reply(self, subject, contents):
        answer = Msg(self.fromAddr, subject, contents)
        answer._replyId = self._msgId
        return answer