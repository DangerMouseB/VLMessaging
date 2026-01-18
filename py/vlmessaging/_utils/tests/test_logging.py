# **********************************************************************************************************************
# Copyright 2026 David Briant, https://github.com/coppertop-bones. Licensed under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance with the License. You may obtain a copy of the  License at
# http://www.apache.org/licenses/LICENSE-2.0. Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY  KIND,
# either express or implied. See the License for the specific language governing permissions and limitations under the
# License. See the NOTICE file distributed with this work for additional information regarding copyright ownership.
# **********************************************************************************************************************

# Python imports
import sys

# vlmessaging imports
from vlmessaging._utils import logging

_logger = logging.getLogger(__name__)


def test_logging():
    root, A, A_B = [], [], []
    FMT = '%-17s:%s'

    loggerRoot = logging.getLogger()
    loggerA = logging.getLogger('A')
    loggerA_B = logging.getLogger('A.B').disable
    
    loggerRoot >> logging.ListSink(root, formatter=logging.Formatter('%(message)s'))
    loggerA >> logging.ListSink(A, formatter=logging.Formatter('%(message)s'))
    loggerA_B >> logging.ListSink(A_B, formatter=logging.Formatter('%(message)s'))

    # text piped *args
    (FMT, 'main', 'some detail') >> loggerRoot.warning
    assert FMT % ('main', 'some detail') in root

    # test logger hierarchy
    'msg1' >> loggerRoot.info       # goes nowhere since default log level is warning
    assert 'msg1' not in root
    assert 'msg1' not in  A
    assert 'msg1' not in  A_B

    'msg2' >> loggerA.warning
    assert 'msg2' in root
    assert 'msg2' in A
    assert 'msg2' not in A_B        # handler set but child of name A

    'msg3' >> loggerA_B.warning     # goes nowhere since logger A.B is disabled
    assert 'msg3' not in root
    assert 'msg3' not in A
    assert 'msg3' not in A_B

    with logging.enable('A.*'):
        'msg4' >> loggerA_B.warning
        assert 'msg4' in root
        assert 'msg4' in A
        assert 'msg4' in A_B

        # test setting all handlers to INFO level
        with logging.configure(levels={
            '*':logging.INFO
        }):
            'msg5' >> loggerA_B.debug       # won't appear since level is INFO
            assert 'msg5' not in root
            assert 'msg5' not in A
            assert 'msg5' not in A_B

            'msg6' >> loggerA_B.info
            assert 'msg6' in root
            assert 'msg6' in A
            assert 'msg6' in A_B

        with logging.configure(levels={
            '*': logging.INFO,
            'A': logging.DEBUG,
            'A.B': logging.DEBUG,
        }):
            'msg7' >> loggerA_B.debug
            assert 'msg7' in root
            assert 'msg7' in A
            assert 'msg7' in A_B

    'test_logging passed' >> _logger.info


if __name__ == '__main__':
    sink = logging.StreamSink(sys.stdout, formatter=logging.Formatter('%(message)s'))
    _logger.setLevel(logging.INFO) >> sink
    test_logging()

