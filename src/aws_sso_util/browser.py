import os
import sys
import textwrap
import webbrowser

from .exceptions import InteractiveAuthDisabledError, AuthDispatchError

class OpenBrowserHandler(object):
    def __init__(self, outfile=None, open_browser=None):
        self._outfile = outfile or sys.stderr
        if open_browser is None:
            open_browser = webbrowser.open_new_tab
        self._open_browser = open_browser

    def __call__(self, userCode, verificationUri,
                 verificationUriComplete, **kwargs):
        message = textwrap.dedent("""\
        AWS SSO login required.
        Attempting to open the SSO authorization page in your default browser.
        If the browser does not open or you wish to use a different device to
        authorize this request, open the following URL:

        {verificationUri}

        Then enter the code:

        {userCode}
        """.format(verificationUri=verificationUri, userCode=userCode))

        print(message, file=sys.stderr)

        disable_browser = os.environ.get('AWS_SSO_DISABLE_BROWSER', '').lower() in ['1', 'true']
        if self._open_browser and not disable_browser:
            try:
                return self._open_browser(verificationUriComplete)
            except InteractiveAuthDisabledError:
                raise
            except Exception as e:
                raise AuthDispatchError('Failed to open browser') from e
                # LOG.debug('Failed to open browser:', exc_info=True)

def non_interactive_auth_raiser(*args, **kwargs):
    raise InteractiveAuthDisabledError
