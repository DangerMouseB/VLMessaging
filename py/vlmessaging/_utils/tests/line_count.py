# **********************************************************************************************************************
# Copyright 2025 David Briant, https://github.com/coppertop-bones. Licensed under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance with the License. You may obtain a copy of the  License at
# http://www.apache.org/licenses/LICENSE-2.0. Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY  KIND,
# either express or implied. See the License for the specific language governing permissions and limitations under the
# License. See the NOTICE file distributed with this work for additional information regarding copyright ownership.
# **********************************************************************************************************************

from coppertop.dm.utils.countlines import folder_linecount

def print_my_stuff():
    opts = ['-r', '-of', '-ofn', '--skipblank']
    py_comments = ['#']

    vlm_all = folder_linecount('~/arwen/VLMessaging/py', ['-r', '-of', '-ofn', '--skipblank'], ['.py'], py_comments, [])
    print(f'----------------- src: {vlm_all} tests: {vlm_all[0]-vlm_all[0], vlm_all[1]-vlm_all[1]}')

    vlm_all = folder_linecount('~/arwen/VLMessaging/py', ['-r', '-of', '--skipblank'], ['.py'], py_comments, [])
    print(f'----------------- src: {vlm_all} tests: {vlm_all[0]-vlm_all[0], vlm_all[1]-vlm_all[1]}')


if __name__ == '__main__':
    print_my_stuff()
