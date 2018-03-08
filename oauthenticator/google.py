"""
Custom Authenticator to use Google OAuth with JupyterHub.

Derived from the GitHub OAuth authenticator.
"""

import os
import json

from tornado             import gen
from tornado.auth        import GoogleOAuth2Mixin
from tornado.web         import HTTPError

from traitlets           import Unicode, Tuple, default

from jupyterhub.auth     import LocalAuthenticator
from jupyterhub.utils    import url_path_join

from .oauth2 import OAuthLoginHandler, OAuthCallbackHandler, OAuthenticator

class GoogleLoginHandler(OAuthLoginHandler, GoogleOAuth2Mixin):
    '''An OAuthLoginHandler that provides scope to GoogleOAuth2Mixin's
       authorize_redirect.'''
    def get(self):
        guess_uri = '{proto}://{host}{path}'.format(
            proto=self.request.protocol,
            host=self.request.host,
            path=url_path_join(
                self.hub.server.base_url,
                'oauth_callback'
            )
        )

        redirect_uri = self.authenticator.oauth_callback_url or guess_uri
        self.log.info('redirect_uri: %r', redirect_uri)

        self.authorize_redirect(
            redirect_uri=redirect_uri,
            client_id=self.authenticator.client_id,
            scope=['openid', 'email'],
            response_type='code')

class GoogleOAuthHandler(OAuthCallbackHandler, GoogleOAuth2Mixin):
    @gen.coroutine
    def get(self):
        self.settings['google_oauth'] = {
            'key': self.authenticator.client_id,
            'secret': self.authenticator.client_secret,
            'scope': ['openid', 'email']
        }
        self.log.debug('google: settings: "%s"', str(self.settings['google_oauth']))
        # FIXME: we should verify self.settings['google_oauth']['hd']

        # "Cannot redirect after headers have been written" ?
        #OAuthCallbackHandler.get(self)
        username = yield self.authenticator.get_authenticated_user(self, None)
        self.log.info('google: username: "%s"', username)
        if username:
            user = self.user_from_username(username)
            self.set_login_cookie(user)
            self.redirect(url_path_join(self.hub.server.base_url, 'home'))
        else:
            # todo: custom error
            raise HTTPError(403)

class GoogleOAuthenticator(OAuthenticator, GoogleOAuth2Mixin):

    login_handler = GoogleLoginHandler
    callback_handler = GoogleOAuthHandler

    hosted_domain = Tuple(
        config=True,
        help="""Hosted domain used to restrict sign-in, e.g. mycollege.edu"""
    )
    login_service = Unicode(
        os.environ.get('LOGIN_SERVICE', 'Google'),
        config=True,
        help="""Google Apps hosted domain string, e.g. My College"""
    )

    @default('hosted_domain')
    def _get_hosted_domain(self):
        domains = os.environ.get('HOSTED_DOMAIN', self.hosted_domain)
        return tuple([domain.strip() for domain in domains.split(',')])

    @gen.coroutine
    def authenticate(self, handler, data=None):
        code = handler.get_argument('code', False)
        if not code:
            raise HTTPError(400, "oauth callback made without a token")
        if not self.oauth_callback_url:
            raise HTTPError(500, "No callback URL")
        user = yield handler.get_authenticated_user(
            redirect_uri=self.oauth_callback_url,
            code=code)
        access_token = str(user['access_token'])

        http_client = handler.get_auth_http_client()

        response = yield http_client.fetch(
            self._OAUTH_USERINFO_URL + '?access_token=' + access_token
        )

        if not response:
            self.clear_all_cookies()
            raise HTTPError(500, 'Google authentication failed')

        body = response.body.decode()
        self.log.debug('response.body.decode(): {}'.format(body))
        bodyjs = json.loads(body)

        username = bodyjs['email']

        self.hosted_domains = self._get_hosted_domain()

        if self.hosted_domains:
            username, _, domain = username.partition('@')
            print(username, _, domain)
            print(self.hosted_domains)
            if not domain in self.hosted_domains or \
                bodyjs['hd'] not in self.hosted_domains:
                raise HTTPError(403,
                    "You are not signed in to your {} account.".format(
                        domain)
                )

        return username

class LocalGoogleOAuthenticator(LocalAuthenticator, GoogleOAuthenticator):
    """A version that mixes in local system user creation"""
    pass
