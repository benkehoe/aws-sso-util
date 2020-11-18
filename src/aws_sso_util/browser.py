# Copyright 2020 Ben Kehoe
#
# Licensed under the Apache License, Version 2.0 (the "License"). You
# may not use this file except in compliance with the License. A copy of
# the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "license" file accompanying this file. This file is
# distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF
# ANY KIND, either express or implied. See the License for the specific
# language governing permissions and limitations under the License.

import os
import sys
import textwrap
import webbrowser

from .exceptions import AuthenticationNeededError, AuthDispatchError

DEFAULT_MESSAGE = textwrap.dedent("""\
AWS SSO login required.
Attempting to open the SSO authorization page in your default browser.
If the browser does not open or you wish to use a different device to
authorize this request, open the following URL:

{url}

Then enter the code:

{code}
""")

class OpenBrowserHandler(object):
    def __init__(self, outfile=None, open_browser=None, message=None):
        if outfile is None:
            outfile = sys.stderr
        self._outfile = outfile

        if open_browser is None:
            open_browser = webbrowser.open_new_tab
        self._open_browser = open_browser

        if not message:
            message = DEFAULT_MESSAGE
        self._message = message

    def __call__(self, userCode, verificationUri,
                 verificationUriComplete, **kwargs):
        message = self._message.format(
            url=verificationUri,
            code=userCode,
            verificationUri=verificationUri,
            userCode=userCode
        )

        if self._outfile:
            print(message, file=self._outfile)

        disable_browser = os.environ.get('AWS_SSO_DISABLE_BROWSER', '').lower() in ['1', 'true']
        if self._open_browser and not disable_browser:
            try:
                return self._open_browser(verificationUriComplete)
            except AuthenticationNeededError:
                raise
            except Exception as e:
                raise AuthDispatchError('Failed to open browser') from e
                # LOG.debug('Failed to open browser:', exc_info=True)

def non_interactive_auth_raiser(*args, **kwargs):
    raise AuthenticationNeededError
