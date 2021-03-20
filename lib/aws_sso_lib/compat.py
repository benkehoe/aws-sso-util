# Copyright 2012-2013 Amazon.com, Inc. or its affiliates. All Rights Reserved.

# Licensed under the Apache License, Version 2.0 (the "License"). You
# may not use this file except in compliance with the License. A copy of
# the License is located at

#     http://aws.amazon.com/apache2.0/

# or in the "license" file accompanying this file. This file is
# distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF
# ANY KIND, either express or implied. See the License for the specific
# language governing permissions and limitations under the License.

# modified from https://github.com/aws/aws-cli/blob/v2/awscli/compat.py

import sys
import shlex

def shell_join(l):
    return ' '.join(shell_quote(arg) for arg in l)

def shell_quote(s, platform=None):
    """Return a shell-escaped version of the string *s*

    Unfortunately `shlex.quote` doesn't support Windows, so this method
    provides that functionality.
    """
    if platform is None:
        platform = sys.platform

    if platform == "win32":
        return _windows_shell_quote(s)
    else:
        return shlex.quote(s)


def _windows_shell_quote(s):
    """Return a Windows shell-escaped version of the string *s*

    Windows has potentially bizarre rules depending on where you look. When
    spawning a process via the Windows C runtime the rules are as follows:

    https://docs.microsoft.com/en-us/cpp/cpp/parsing-cpp-command-line-arguments

    To summarize the relevant bits:

    * Only space and tab are valid delimiters
    * Double quotes are the only valid quotes
    * Backslash is interpreted literally unless it is part of a chain that
      leads up to a double quote. Then the backslashes escape the backslashes,
      and if there is an odd number the final backslash escapes the quote.

    :param s: A string to escape
    :return: An escaped string
    """
    if not s:
        return '""'

    buff = []
    num_backspaces = 0
    for character in s:
        if character == '\\':
            # We can't simply append backslashes because we don't know if
            # they will need to be escaped. Instead we separately keep track
            # of how many we've seen.
            num_backspaces += 1
        elif character == '"':
            if num_backspaces > 0:
                # The backslashes are part of a chain that lead up to a
                # double quote, so they need to be escaped.
                buff.append('\\' * (num_backspaces * 2))
                num_backspaces = 0

            # The double quote also needs to be escaped. The fact that we're
            # seeing it at all means that it must have been escaped in the
            # original source.
            buff.append('\\"')
        else:
            if num_backspaces > 0:
                # The backslashes aren't part of a chain leading up to a
                # double quote, so they can be inserted directly without
                # being escaped.
                buff.append('\\' * num_backspaces)
                num_backspaces = 0
            buff.append(character)

    # There may be some leftover backspaces if they were on the trailing
    # end, so they're added back in here.
    if num_backspaces > 0:
        buff.append('\\' * num_backspaces)

    new_s = ''.join(buff)
    if ' ' in new_s or '\t' in new_s:
        # If there are any spaces or tabs then the string needs to be double
        # quoted.
        return '"%s"' % new_s
    return new_s
