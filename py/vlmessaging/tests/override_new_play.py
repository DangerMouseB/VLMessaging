# **********************************************************************************************************************
# Copyright 2025 David Briant, https://github.com/coppertop-bones. Licensed under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance with the License. You may obtain a copy of the  License at
# http://www.apache.org/licenses/LICENSE-2.0. Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY  KIND,
# either express or implied. See the License for the specific language governing permissions and limitations under the
# License. See the NOTICE file distributed with this work for additional information regarding copyright ownership.
# **********************************************************************************************************************

import inspect


def decorator(cls):
    # https://docs.python.org/3.11/library/functions.html#super

    orig_new = cls.__new__
    orig_init = cls.__init__

    def new_new(cls, *args, **kwargs):
        print(f'{cls.__name__}.orig_new({", ".join(str(p) for p in inspect.signature(orig_new).parameters.values())})')
        print(f'{cls.__name__}.orig_init({", ".join(str(p) for p in inspect.signature(orig_init).parameters.values())})')
        try:
            inst = orig_new(*((cls,) + args), **kwargs)
        except TypeError as ex:
            # we can't generically handle this as we don't know how to map child class args to parent class args
            # however let's try one common case where __new__ takes only cls as argument since parent is object
            try:
                if not ex.args[0].startswith('object.__new__() takes exactly one argument (the type to instantiate)'):
                    print(ex)
                inst = orig_new(cls, **kwargs)
            except TypeError as ex2:
                if not ex.args[0].startswith('object.__new__() takes exactly one argument (the type to instantiate)'):
                    print(ex)
                inst = orig_new(cls)
        return inst

    cls.__new__ = new_new
    return cls


@decorator
class Fred:
    pass

@decorator
class Joe:
    def __new__(cls, *args, **kwargs):
        print(f'Joe.__new__')
        inst = super(cls, cls).__new__(cls)
        return inst

@decorator
class Sally:
    def __init__(self, *args, **kwargs):
        print(f'Sally __init__')
        super(self.__class__, self).__init__()
        (a := super()).__init__()
        (b := super(Sally)).__init__(Sally)
        (c := super(Sally, self)).__init__()
        (d := super(Sally, Sally)).__init__(self)

@decorator
class Arthur:
    def __new__(cls, *args, **kwargs):
        print(f'Arthur __new__')
        inst = super().__new__(cls)
        return inst
    def __init__(self, *args, **kwargs):
        print(f'Arthur __init__')
        super(self.__class__, self).__init__()



def test_add_one_to_current():
    f = Fred()
    j = Joe()
    s = Sally(1)
    a = Arthur(1)
    s = Sally(1, a=1)


def main():
    test_add_one_to_current()
    print('passed')


if __name__ == '__main__':
    main()