# **********************************************************************************************************************
# Copyright 2025 David Briant, https://github.com/coppertop-bones. Licensed under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance with the License. You may obtain a copy of the  License at
# http://www.apache.org/licenses/LICENSE-2.0. Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY  KIND,
# either express or implied. See the License for the specific language governing permissions and limitations under the
# License. See the NOTICE file distributed with this work for additional information regarding copyright ownership.
# **********************************************************************************************************************

# Python imports
import sys


handlersByErrSiteId = {}

def _ensureErrors():
    # general exceptions occuring in coppertop-bones

    if not hasattr(sys, '_CPTBError'):
        class CPTBError(Exception):
            def __str__(self):
                if len(self.args) == 0:
                    return super().__str__()
                if len(self.args) == 1:
                    return self.args[0]
                elif len(self.args) == 2:
                    msg, errSite = self.args
                    return msg + f" ({errSite})"
                else:
                    return self.args[0] + f" ({self.args[1:]})"
        sys._CPTBError = CPTBError
    CPTBError = sys._CPTBError

    if not hasattr(sys, '_ProgrammerError'):
        class ProgrammerError(CPTBError): pass
        sys._ProgrammerError = ProgrammerError

    if not hasattr(sys, '_NotYetImplemented'):
        class NotYetImplemented(CPTBError): pass
        sys._NotYetImplemented = NotYetImplemented

    if not hasattr(sys, '_PathNotTested'):
        class PathNotTested(CPTBError): pass
        sys._PathNotTested = PathNotTested

    if not hasattr(sys, '_UnhappyWomble'):
        class UnhappyWomble(CPTBError): pass
        sys._UnhappyWomble = UnhappyWomble

    if not hasattr(sys, '_WTF'):        # polite interpretation pls - What The Flip, What The Frac
        class WTF(CPTBError): pass
        sys._WTF = WTF

    if not hasattr(sys, '_ImpossiblePathError'):
        class ImpossiblePathError(CPTBError): pass
        sys._ImpossiblePathError = ImpossiblePathError


_ensureErrors()
CPTBError = sys._CPTBError
ProgrammerError = sys._ProgrammerError
NotYetImplemented = sys._NotYetImplemented
PathNotTested = sys._PathNotTested
UnhappyWomble = sys._UnhappyWomble
WTF = sys._WTF
ImpossiblePathError = sys._ImpossiblePathError


_ignore = [
    'IPython', 'ipykernel', 'pydevd', 'coppertop.pipe', '_pydev_imps._pydev_execfile', 'tornado', 'runpy', 'asyncio',
    'traitlets'
]
