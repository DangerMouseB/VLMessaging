# **********************************************************************************************************************
# Copyright 2025 David Briant, https://github.com/coppertop-bones. Licensed under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance with the License. You may obtain a copy of the  License at
# http://www.apache.org/licenses/LICENSE-2.0. Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY  KIND,
# either express or implied. See the License for the specific language governing permissions and limitations under the
# License. See the NOTICE file distributed with this work for additional information regarding copyright ownership.
# **********************************************************************************************************************



def with_async_init(cls):
    # baseed on https://gist.github.com/AnoRebel/433110fcf589dba6f26ea6cf8c3320a4 - AnoRebel/asyncinit.py

    # override __new__ with replacement_new, which, instead of directly returning the new instance, returns a
    # coroutine, __async_init__, that first does `new_inst.__init__(*args, **kwargs)` before returning the newly
    # created instance. Python will still call __init__ after __new__, but since __init__ is a coroutine, it won't
    # do anything.

    orig_new = cls.__new__

    async def __async_init__(new_inst, *args, **kwargs):
        await new_inst.__init__(*args, **kwargs)
        return new_inst

    def replacement_new(cls, *args, **kwargs):
        try:
            new_inst = orig_new(cls, *args, **kwargs)
        except TypeError:
            #  handle case where __new__ takes no arguments - see override_new_play.py for more details
            new_inst = orig_new(cls)
        return __async_init__(new_inst, *args, **kwargs)

    cls.__new__ = replacement_new
    return cls
