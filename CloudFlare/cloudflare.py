""" Cloudflare v4 API"""
import json
import keyword
from requests import RequestException as requests_RequestException, ConnectionError as requests_ConnectionError, exceptions as requests_exceptions, codes as requests_codes

from .network import CFnetwork
from .logging_helper import CFlogger
from .utils import user_agent, build_curl
from .read_configs import read_configs
from .api_v4 import api_v4
from .api_extras import api_extras
from .api_decode_from_web import api_decode_from_web
from .api_decode_from_openapi import api_decode_from_openapi
from .exceptions import CloudFlareError, CloudFlareAPIError, CloudFlareInternalError

BASE_URL = 'https://api.cloudflare.com/client/v4'

class CloudFlare():
    """ Cloudflare v4 API"""

    class _v4base():
        """ Cloudflare v4 API"""

        def __init__(self, config):
            """ Cloudflare v4 API"""

            self.config = config

            self.api_email = config['email'] if 'email' in config else None
            self.api_key = config['key'] if 'key' in config else None
            self.api_token = config['token'] if 'token' in config else None
            self.api_certtoken = config['certtoken'] if 'certtoken' in config else None

            # We must have a base_url value
            self.base_url = config['base_url'] if 'base_url' in config else BASE_URL

            self.raw = config['raw']
            self.use_sessions = config['use_sessions']
            self.global_request_timeout = config['global_request_timeout'] if 'global_request_timeout' in config else None
            self.max_request_retries = config['max_request_retries'] if 'max_request_retries' in config else None
            self.profile = config['profile']
            self.network = CFnetwork(
                use_sessions=self.use_sessions,
                global_request_timeout=self.global_request_timeout,
                max_request_retries=self.max_request_retries
            )
            self.user_agent = user_agent()

            self.logger = CFlogger(config['debug']).getLogger() if 'debug' in config and config['debug'] else None

        def __del__(self):
            if self.network:
                del self.network
                self.network = None

        def _add_headers(self, headers):
            """ Add default headers """
            headers['User-Agent'] = self.user_agent
            headers['Content-Type'] = 'application/json'

        def _add_auth_headers(self, headers, method):
            """ Add authentication headers """

            v = 'email' + '.' + method.lower()
            api_email = self.config[v] if v in self.config else self.api_email
            v = 'key' + '.' + method.lower()
            api_key = self.config[v] if v in self.config else self.api_key
            v = 'token' + '.' + method.lower()
            api_token = self.config[v] if v in self.config else self.api_token

            if api_email is None and api_key is None and api_token is None:
                raise CloudFlareAPIError(0, 'neither email/key or token defined')

            if api_key is not None and api_token is not None:
                raise CloudFlareAPIError(0, 'confused info - both key and token defined')

            if api_email is not None and api_key is None and api_token is None:
                raise CloudFlareAPIError(0, 'email defined however neither key or token defined')

            # We know at this point that at-least one api_* is set and no confusion!

            if api_email is None and api_token is not None:
                # post issue-114 - token is used
                headers['Authorization'] = 'Bearer %s' % (api_token)
            elif api_email is None and api_key is not None:
                # pre issue-114 - key is used vs token - backward compat
                headers['Authorization'] = 'Bearer %s' % (api_key)
            elif api_email is not None and api_key is not None:
                # boring old school email/key methodology (token ignored)
                headers['X-Auth-Email'] = api_email
                headers['X-Auth-Key'] = api_key
            elif api_email is not None and api_token is not None:
                # boring old school email/key methodology (token ignored)
                headers['X-Auth-Email'] = api_email
                headers['X-Auth-Key'] = api_token
            else:
                raise CloudFlareInternalError(0, 'coding issue!')

        def _add_certtoken_headers(self, headers, method):
            """ Add authentication headers """

            v = 'certtoken' + '.' + method.lower()
            if v in self.config:
                api_certtoken = self.config[v] # use specific value for this method
            else:
                api_certtoken = self.api_certtoken # use generic value for all methods

            if api_certtoken is None:
                raise CloudFlareAPIError(0, 'no cert token defined')
            headers['X-Auth-User-Service-Key'] = api_certtoken

        def do_no_auth(self, method, parts, identifiers, params=None, data=None, files=None):
            """ Cloudflare v4 API"""

            headers = {}
            self._add_headers(headers)
            return self._call(method, headers, parts, identifiers, params, data, files)

        def do_auth(self, method, parts, identifiers, params=None, data=None, files=None):
            """ Cloudflare v4 API"""

            headers = {}
            self._add_headers(headers)
            self._add_auth_headers(headers, method)
            if isinstance(data, str):
                # passing javascript vs JSON
                headers['Content-Type'] = 'application/javascript'
            if files:
                # overwrite Content-Type as we are uploading data
                headers['Content-Type'] = 'multipart/form-data'
                # however something isn't right and this works ... look at again later!
                del headers['Content-Type']
            return self._call(method, headers, parts, identifiers, params, data, files)

        def do_auth_unwrapped(self, method, parts, identifiers, params=None, data=None, files=None):
            """ Cloudflare v4 API"""

            headers = {}
            self._add_headers(headers)
            self._add_auth_headers(headers, method)
            if isinstance(data, str):
                # passing javascript vs JSON
                headers['Content-Type'] = 'application/javascript'
            if files:
                # overwrite Content-Type as we are uploading data
                headers['Content-Type'] = 'multipart/form-data'
                # however something isn't right and this works ... look at again later!
                del headers['Content-Type']
            return self._call_unwrapped(method, headers, parts, identifiers, params, data, files)

        def do_certauth(self, method, parts, identifiers, params=None, data=None, files=None):
            """ Cloudflare v4 API"""

            headers = {}
            self._add_headers(headers)
            self._add_certtoken_headers(headers, method)
            return self._call(method, headers, parts, identifiers, params, data, files)

        def _call_network(self, method, headers, parts, identifiers, params, data, files):
            """ Cloudflare v4 API"""

            if (method is None) or (parts[0] is None):
                # should never happen
                raise CloudFlareInternalError(0, 'You must specify a method and endpoint')

            # By this point we know that parts[] has 5 elements and identifiers[] has 4 elements (even if some are None)

            if parts[1] is not None or (data is not None and method == 'GET'):
                if identifiers[0] is None:
                    raise CloudFlareAPIError(0, 'You must specify first identifier')
                if identifiers[1] is None:
                    url = (self.base_url + '/'
                           + parts[0] + '/'
                           + identifiers[0] + '/'
                           + parts[1])
                else:
                    url = (self.base_url + '/'
                           + parts[0] + '/'
                           + identifiers[0] + '/'
                           + parts[1] + '/'
                           + identifiers[1])
            else:
                if identifiers[0] is None:
                    url = (self.base_url + '/'
                           + parts[0])
                else:
                    url = (self.base_url + '/'
                           + parts[0] + '/'
                           + identifiers[0])
            if parts[2]:
                url += '/' + parts[2]
                if identifiers[2]:
                    url += '/' + identifiers[2]
                if parts[3]:
                    url += '/' + parts[3]
                    if identifiers[3]:
                        url += '/' + identifiers[3]
                    if parts[4]:
                        url += '/' + parts[4]

            if files and data:
                # Can't send data and form data - so move data into files and send as multipart/form-data
                new_files = []
                new_files += [(f, (files[f].name, files[f])) for f in files]
                new_files += [(d, (None, data[d])) for d in data]
                files = tuple(new_files)
                data = None

            if self.logger:
                msg = build_curl(method, url, headers, params, data, files)
                self.logger.debug('Call: emulated curl command ...\n%s', msg)

            try:
                response = self.network(method, url, headers, params, data, files)
            except requests_RequestException as e:
                if self.logger:
                    self.logger.debug('Call: requests exception! "%s"', e)
                raise CloudFlareAPIError(0, e)
            except requests_ConnectionError as e:
                if self.logger:
                    self.logger.debug('Call: requests connection exception! "%s"', e)
                raise CloudFlareAPIError(0, 'connection error')
            except requests_exceptions.Timeout as e:
                if self.logger:
                    self.logger.debug('Call: requests timeout exception! "%s"', e)
                raise CloudFlareAPIError(0, 'connection timeout')
            except Exception as e:
                if self.logger:
                    self.logger.debug('Call: exception! "%s"', e)
                raise

            # Create response_{type|code|data}
            try:
                response_type = response.headers['Content-Type']
                if ';' in response_type:
                    # remove the ;paramaters part (like charset=, etc.)
                    response_type = response_type[0:response_type.rfind(';')]
                response_type = response_type.strip().lower()
            except:
                # API should always response; but if it doesn't; here's the default
                response_type = 'application/octet-stream'
            response_code = response.status_code
            response_data = response.content
            if not isinstance(response_data, (str, bytes, bytearray)):
                response_data = response_data.decode("utf-8")

            if self.logger:
                self.logger.debug('Response: %d, %s, %s', response_code, response_type, response_data)

            if response_code >= 500 and response_code <= 599:
                # 500 Internal Server Error
                # 501 Not Implemented
                # 502 Bad Gateway
                # 503 Service Unavailable
                # 504 Gateway Timeout
                # 505 HTTP Version Not Supported
                # 506 Variant Also Negotiates
                # 507 Insufficient Storage
                # 508 Loop Detected
                # 509 Unassigned
                # 510 Not Extended
                # 511 Network Authentication Required

                # the libary doesn't deal with these errors, just pass upwards!
                # there's no value to add and the returned data is questionable or not useful
                response.raise_for_status()

                # should not be reached
                raise CloudFlareInternalError(0, 'internal error in status code processing')

            #if response_code >= 400 and response_code <= 499:
            #    # 400 Bad Request
            #    # 401 Unauthorized
            #    # 403 Forbidden
            #    # 405 Method Not Allowed
            #    # 415 Unsupported Media Type
            #    # 429 Too many requests
            #
            #    # don't deal with these errors, just pass upwards!
            #    response.raise_for_status()
            #
            #if response_code >= 300 and response_code <= 399:
            #    # 304 Not Modified
            #
            #    # don't deal with these errors, just pass upwards!
            #    response.raise_for_status()
            #
            # should be a 200 response at this point

            return [response_type, response_code, response_data]

        def _raw(self, method, headers, parts, identifiers, params, data, files):
            """ Cloudflare v4 API"""

            [response_type, response_code, response_data] = self._call_network(method,
                                                                               headers, parts,
                                                                               identifiers,
                                                                               params, data, files)

            if response_type == 'application/json':
                # API says it's JSON; so it better be parsable as JSON
                # NDJSON is returned by Enterprise Log Share i.e. /zones/:id/logs/received
                if hasattr(response_data, 'decode'):
                    response_data = response_data.decode('utf-8')
                try:
                    response_data = json.loads(response_data)
                    if not isinstance(response_data, (dict)):
                        response_data = {'success': True,
                                         'result': response_data}
                except ValueError:
                    if response_data == '':
                        # This should really be 'null' but it isn't. Even then, it's wrong!
                        if response_code == requests_codes.ok:
                            # 200 ok
                            response_data = {'success': True,
                                             'result': None}
                        else:
                            # 3xx & 4xx errors
                            response_data = {'success': False,
                                             'code': response_code,
                                             'result': None}
                    else:
                        # Lets see if it's NDJSON data
                        # NDJSON is a series of JSON elements with newlines between each element
                        try:
                            r = []
                            for l in response_data.splitlines():
                                r.append(json.loads(l))
                            response_data = r
                        except:
                            # While this should not happen; it's always possible
                            if self.logger:
                                self.logger.debug('Response data not JSON: %r', response_data)
                            raise CloudFlareAPIError(0, 'JSON parse failed - report to Cloudflare.')

                if response_code == requests_codes.ok:
                    # 200 ok - so nothing needs to be done
                    pass
                else:
                    # 3xx & 4xx errors - we should report that somehow - but not quite yet
                    # response_data['code'] = response_code
                    pass
            elif response_type == 'application/octet-stream' and isinstance(response_data, (int, float)):
                # It's binary data
                if response_code == requests_codes.ok:
                    # 200 ok
                    response_data = {'success': True,
                                     'result': response_data}
                else:
                    # 3xx & 4xx errors
                    response_data = {'success': False,
                                     'code': response_code,
                                     'result': response_data}
            elif response_type == 'application/octet-stream' and isinstance(response_data, (bytes, bytearray)):
                # API says it's text; but maybe it's actually JSON? - should be fixed in API
                if hasattr(response_data, 'decode'):
                    response_data = response_data.decode('utf-8')
                try:
                    response_data = json.loads(response_data)
                    if not isinstance(response_data, (dict)) or 'success' not in response_data:
                        if response_code == requests_codes.ok:
                            # 200 ok
                            response_data = {'success': True,
                                             'result': response_data}
                        else:
                            # 3xx & 4xx errors
                            response_data = {'success': False,
                                             'code': response_code,
                                             'result': response_data}
                except ValueError:
                    # So it wasn't JSON - moving on as if it's text!
                    # A single value is returned (vs an array or object)
                    if response_code == requests_codes.ok:
                        # 200 ok
                        response_data = {'success': True, 'result': response_data}
                    else:
                        # 3xx & 4xx errors
                        response_data = {'success': False,
                                         'code': response_code,
                                         'result': response_data}
            elif response_type in ['text/plain', 'application/octet-stream']:
                # API says it's text; but maybe it's actually JSON? - should be fixed in API
                if hasattr(response_data, 'decode'):
                    response_data = response_data.decode('utf-8')
                try:
                    response_data = json.loads(response_data)
                    if not isinstance(response_data, (dict)):
                        response_data = {'success': True,
                                         'result': response_data}
                except ValueError:
                    # So it wasn't JSON - moving on as if it's text!
                    # A single value is returned (vs an array or object)
                    if response_code == requests_codes.ok:
                        # 200 ok
                        response_data = {'success': True, 'result': response_data}
                    else:
                        # 3xx & 4xx errors
                        response_data = {'success': False,
                                         'code': response_code,
                                         'result': response_data}
            elif response_type in ['text/javascript', 'application/javascript']:
                # used by Cloudflare workers
                if response_code == requests_codes.ok:
                    # 200 ok
                    response_data = {'success': True,
                                     'result': str(response_data)}
                else:
                    # 3xx & 4xx errors
                    response_data = {'success': False,
                                     'code': response_code,
                                     'result': str(response_data)}
            elif response_type == 'text/html':
                # used by media for preview
                if response_code == requests_codes.ok:
                    # 200 ok
                    response_data = {'success': True,
                                     'result': str(response_data)}
                else:
                    # 3xx & 4xx errors
                    response_data = {'success': False,
                                     'code': response_code,
                                     'result': str(response_data)}

            else:
                # Assuming nothing - but continuing anyway
                # A single value is returned (vs an array or object)
                if response_code == requests_codes.ok:
                    # 200 ok
                    response_data = {'success': True,
                                     'result': str(response_data)}
                else:
                    # 3xx & 4xx errors
                    response_data = {'success': False,
                                     'code': response_code,
                                     'result': str(response_data)}

            # it would be nice to return the error code and content type values; but not quite yet
            return response_data

        def _call(self, method, headers, parts, identifiers, params, data, files):
            """ Cloudflare v4 API"""

            response_data = self._raw(method, headers, parts, identifiers, params, data, files)

            # Sanatize the returned results - just in case API is messed up
            if 'success' not in response_data:
                if 'errors' in response_data:
                    if response_data['errors'] is None:
                        # Only happens on /graphql call
                        if self.logger:
                            self.logger.debug('Response: assuming success = "True"')
                        response_data['success'] = True
                    else:
                        if self.logger:
                            self.logger.debug('Response: assuming success = "False"')
                        # The following only happens on /graphql call
                        try:
                            message = response_data['errors'][0]['message']
                        except:
                            message = ''
                        try:
                            location = str(response_data['errors'][0]['location'])
                        except:
                            location = ''
                        try:
                            path = '>'.join(response_data['errors'][0]['path'])
                        except:
                            path = ''
                        response_data['errors'] = [{'code': 99999, 'message': message + ' - ' + location + ' - ' + path}]
                        response_data['success'] = False
                else:
                    if 'result' not in response_data:
                        # Only happens on /certificates call
                        # should be fixed in /certificates API
                        if self.logger:
                            self.logger.debug('Response: assuming success = "False"')
                        r = response_data
                        response_data['errors'] = []
                        response_data['errors'].append(r)
                        response_data['success'] = False
                    else:
                        if self.logger:
                            self.logger.debug('Response: assuming success = "True"')
                        response_data['success'] = True

            if response_data['success'] is False:
                if 'errors' in response_data and response_data['errors'] is not None:
                    errors = response_data['errors'][0]
                else:
                    errors = {}
                if 'code' in errors:
                    code = errors['code']
                else:
                    code = 99998
                if 'message' in errors:
                    message = errors['message']
                elif 'error' in errors:
                    message = errors['error']
                else:
                    message = ''
                ##if 'messages' in response_data:
                ##    errors['error_chain'] = response_data['messages']
                if 'error_chain' in errors:
                    error_chain = errors['error_chain']
                    for error in error_chain:
                        if self.logger:
                            self.logger.debug('Response: error %d %s - chain', error['code'], error['message'])
                    if self.logger:
                        self.logger.debug('Response: error %d %s', code, message)
                    raise CloudFlareAPIError(code, message, error_chain)
                else:
                    if self.logger:
                        self.logger.debug('Response: error %d %s', code, message)
                    raise CloudFlareAPIError(code, message)

            if self.raw:
                result = {}
                # theres always a result value - unless it's a graphql query
                try:
                    result['result'] = response_data['result']
                except:
                    result['result'] = response_data
                # theres may not be a result_info on every call
                if 'result_info' in response_data:
                    result['result_info'] = response_data['result_info']
                # no need to return success, errors, or messages as they return via an exception
            else:
                # theres always a result value - unless it's a graphql query
                try:
                    result = response_data['result']
                except:
                    result = response_data
            if self.logger:
                self.logger.debug('Response: %s', result)
            return result

        def _call_unwrapped(self, method, headers, parts, identifiers, params, data, files):
            """ Cloudflare v4 API"""

            response_data = self._raw(method, headers, parts, identifiers, params, data, files)
            if self.logger:
                self.logger.debug('Response: %s', response_data)
            result = response_data
            return result

        def api_from_openapi(self, url):
            """ Cloudflare v4 API"""

            return self._read_from_web(url)

        def _read_from_web(self, url):
            """ Cloudflare v4 API"""
            try:
                if self.logger:
                    self.logger.debug('Call: doit!')
                response = self.network('GET', url)
                if self.logger:
                    self.logger.debug('Call: done!')
            except Exception as e:
                if self.logger:
                    self.logger.debug('Call: exception! "%s"', e)
                raise CloudFlareAPIError(0, 'connection failed.')

            return response.text

    class _add_unused():
        """ Cloudflare v4 API"""

        def __init__(self, base, parts):
            """ Cloudflare v4 API"""

            self._base = base
            self._parts_unused = parts

        def __call__(self, identifier1=None, identifier2=None, identifier3=None, identifier4=None, params=None, data=None):
            """ Cloudflare v4 API"""

            # This is the same as a get()
            return self.get(identifier1, identifier2, identifier3, identifier4, params=params, data=data)

        def __str__(self):
            """ Cloudflare v4 API"""

            return '[%s]' % ('/' + '/:id/'.join(filter(None, self._parts_unused)))

        def get(self, identifier1=None, identifier2=None, identifier3=None, identifier4=None, params=None, data=None):
            """ Cloudflare v4 API"""

            raise CloudFlareAPIError(0, 'not found')

        def patch(self, identifier1=None, identifier2=None, identifier3=None, identifier4=None, params=None, data=None):
            """ Cloudflare v4 API"""

            raise CloudFlareAPIError(0, 'not found')

        def post(self, identifier1=None, identifier2=None, identifier3=None, identifier4=None, params=None, data=None, files=None):
            """ Cloudflare v4 API"""

            raise CloudFlareAPIError(0, 'not found')

        def put(self, identifier1=None, identifier2=None, identifier3=None, identifier4=None, params=None, data=None):
            """ Cloudflare v4 API"""

            raise CloudFlareAPIError(0, 'not found')

        def delete(self, identifier1=None, identifier2=None, identifier3=None, identifier4=None, params=None, data=None):
            """ Cloudflare v4 API"""

            raise CloudFlareAPIError(0, 'not found')

    class _add_no_auth():
        """ Cloudflare v4 API"""

        def __init__(self, base, parts):
            """ Cloudflare v4 API"""

            self._base = base
            self._parts = parts

        def __call__(self, identifier1=None, identifier2=None, identifier3=None, identifier4=None, params=None, data=None):
            """ Cloudflare v4 API"""

            # This is the same as a get()
            return self.get(identifier1, identifier2, identifier3, identifier4, params=params, data=data)

        def __str__(self):
            """ Cloudflare v4 API"""

            return '[%s]' % ('/' + '/:id/'.join(filter(None, self._parts)))

        def get(self, identifier1=None, identifier2=None, identifier3=None, identifier4=None, params=None, data=None):
            """ Cloudflare v4 API"""

            return self._base.do_no_auth('GET', self._parts, [identifier1, identifier2, identifier3, identifier4], params, data)

        def patch(self, identifier1=None, identifier2=None, identifier3=None, identifier4=None, params=None, data=None):
            """ Cloudflare v4 API"""

            raise CloudFlareAPIError(0, 'patch() call not available for this endpoint')

        def post(self, identifier1=None, identifier2=None, identifier3=None, identifier4=None, params=None, data=None, files=None):
            """ Cloudflare v4 API"""

            raise CloudFlareAPIError(0, 'post() call not available for this endpoint')

        def put(self, identifier1=None, identifier2=None, identifier3=None, identifier4=None, params=None, data=None):
            """ Cloudflare v4 API"""

            raise CloudFlareAPIError(0, 'put() call not available for this endpoint')

        def delete(self, identifier1=None, identifier2=None, identifier3=None, identifier4=None, params=None, data=None):
            """ Cloudflare v4 API"""

            raise CloudFlareAPIError(0, 'delete() call not available for this endpoint')

    class _add_with_auth():
        """ Cloudflare v4 API"""

        def __init__(self, base, parts):
            """ Cloudflare v4 API"""

            self._base = base
            self._parts = parts

        def __call__(self, identifier1=None, identifier2=None, identifier3=None, identifier4=None, params=None, data=None):
            """ Cloudflare v4 API"""

            # This is the same as a get()
            return self.get(identifier1, identifier2, identifier3, identifier4, params=params, data=data)

        def __str__(self):
            """ Cloudflare v4 API"""

            return '[%s]' % ('/' + '/:id/'.join(filter(None, self._parts)))

        def get(self, identifier1=None, identifier2=None, identifier3=None, identifier4=None, params=None, data=None):
            """ Cloudflare v4 API"""

            return self._base.do_auth('GET', self._parts, [identifier1, identifier2, identifier3, identifier4], params, data)

        def patch(self, identifier1=None, identifier2=None, identifier3=None, identifier4=None, params=None, data=None):
            """ Cloudflare v4 API"""

            return self._base.do_auth('PATCH', self._parts, [identifier1, identifier2, identifier3, identifier4], params, data)

        def post(self, identifier1=None, identifier2=None, identifier3=None, identifier4=None, params=None, data=None, files=None):
            """ Cloudflare v4 API"""

            return self._base.do_auth('POST', self._parts, [identifier1, identifier2, identifier3, identifier4], params, data, files)

        def put(self, identifier1=None, identifier2=None, identifier3=None, identifier4=None, params=None, data=None):
            """ Cloudflare v4 API"""

            return self._base.do_auth('PUT', self._parts, [identifier1, identifier2, identifier3, identifier4], params, data)

        def delete(self, identifier1=None, identifier2=None, identifier3=None, identifier4=None, params=None, data=None):
            """ Cloudflare v4 API"""

            return self._base.do_auth('DELETE', self._parts, [identifier1, identifier2, identifier3, identifier4], params, data)

    class _add_with_auth_unwrapped():
        """ Cloudflare v4 API"""

        def __init__(self, base, parts):
            """ Cloudflare v4 API"""

            self._base = base
            self._parts = parts

        def __call__(self, identifier1=None, identifier2=None, identifier3=None, identifier4=None, params=None, data=None):
            """ Cloudflare v4 API"""

            # This is the same as a get()
            return self.get(identifier1, identifier2, identifier3, identifier4, params=params, data=data)

        def __str__(self):
            """ Cloudflare v4 API"""

            return '[%s]' % ('/' + '/:id/'.join(filter(None, self._parts)))

        def get(self, identifier1=None, identifier2=None, identifier3=None, identifier4=None, params=None, data=None):
            """ Cloudflare v4 API"""

            return self._base.do_auth_unwrapped('GET', self._parts, [identifier1, identifier2, identifier3, identifier4], params, data)

        def patch(self, identifier1=None, identifier2=None, identifier3=None, identifier4=None, params=None, data=None):
            """ Cloudflare v4 API"""

            return self._base.do_auth_unwrapped('PATCH', self._parts, [identifier1, identifier2, identifier3, identifier4], params, data)

        def post(self, identifier1=None, identifier2=None, identifier3=None, identifier4=None, params=None, data=None, files=None):
            """ Cloudflare v4 API"""

            return self._base.do_auth_unwrapped('POST', self._parts, [identifier1, identifier2, identifier3, identifier4], params, data, files)

        def put(self, identifier1=None, identifier2=None, identifier3=None, identifier4=None, params=None, data=None):
            """ Cloudflare v4 API"""

            return self._base.do_auth_unwrapped('PUT', self._parts, [identifier1, identifier2, identifier3, identifier4], params, data)

        def delete(self, identifier1=None, identifier2=None, identifier3=None, identifier4=None, params=None, data=None):
            """ Cloudflare v4 API"""

            return self._base.do_auth_unwrapped('DELETE', self._parts, [identifier1, identifier2, identifier3, identifier4], params, data)

    class _add_with_cert_auth():
        """ Cloudflare v4 API"""

        def __init__(self, base, parts):
            """ Cloudflare v4 API"""

            self._base = base
            self._parts = parts

        def __call__(self, identifier1=None, identifier2=None, identifier3=None, identifier4=None, params=None, data=None):
            """ Cloudflare v4 API"""

            # This is the same as a get()
            return self.get(identifier1, identifier2, identifier3, identifier4, params=params, data=data)

        def __str__(self):
            """ Cloudflare v4 API"""

            return '[%s]' % ('/' + '/:id/'.join(filter(None, self._parts)))

        def get(self, identifier1=None, identifier2=None, identifier3=None, identifier4=None, params=None, data=None):
            """ Cloudflare v4 API"""

            return self._base.do_certauth('GET', self._parts, [identifier1, identifier2, identifier3, identifier4], params, data)

        def patch(self, identifier1=None, identifier2=None, identifier3=None, identifier4=None, params=None, data=None):
            """ Cloudflare v4 API"""

            return self._base.do_certauth('PATCH', self._parts, [identifier1, identifier2, identifier3, identifier4], params, data)

        def post(self, identifier1=None, identifier2=None, identifier3=None, identifier4=None, params=None, data=None, files=None):
            """ Cloudflare v4 API"""

            return self._base.do_certauth('POST', self._parts, [identifier1, identifier2, identifier3, identifier4], params, data, files)

        def put(self, identifier1=None, identifier2=None, identifier3=None, identifier4=None, params=None, data=None):
            """ Cloudflare v4 API"""

            return self._base.do_certauth('PUT', self._parts, [identifier1, identifier2, identifier3, identifier4], params, data)

        def delete(self, identifier1=None, identifier2=None, identifier3=None, identifier4=None, params=None, data=None):
            """ Cloudflare v4 API"""

            return self._base.do_certauth('DELETE', self._parts, [identifier1, identifier2, identifier3, identifier4], params, data)

    def add(self, t, p1, p2=None, p3=None, p4=None, p5=None):
        """add api call to class"""

        a = []
        if p1:
            a += p1.split('/')
        if p2:
            a += p2.split('/')
        if p3:
            a += p3.split('/')
        if p4:
            a += p4.split('/')
        if p5:
            a += p5.split('/')

        parts = [p1, p2, p3, p4, p5]

        branch = self
        for element in a[0:-1]:
            try:
                if '-' in element:
                    branch = getattr(branch, element.replace('-','_'))
                else:
                    branch = getattr(branch, element)
            except AttributeError:
                # missing path - should never happen unless api_v4 is a busted file
                branch = None
                break

        if not branch:
                raise CloudFlareAPIError(0, 'api load: element **%s** missing when adding path /%s' % (element, '/'.join(a)))

        name = a[-1]
        try:
            if keyword.iskeyword(name):
                ## add the keyword appended with an extra underscore so it can used with Python code
                f = getattr(branch, name + '_')
            else:
                if '-' in name:
                    # dashes (vs underscores) cause issues in Python and other languages
                    f = getattr(branch, name.replace('-','_'))
                else:
                    f = getattr(branch, name)
            # we only are here becuase the name already exists - don't let it overwrite - should never happen unless api_v4 is a busted file
            raise CloudFlareAPIError(0, 'api load: duplicate name found: %s/**%s**' % ('/'.join(a[0:-1]), name))
        except AttributeError:
            # this is the required behavior - i.e. it's a new node to create
            pass

        if t == 'VOID':
            f = self._add_unused(self._base, parts)
        elif t == 'OPEN':
            f = self._add_no_auth(self._base, parts)
        elif t == 'AUTH':
            f = self._add_with_auth(self._base, parts)
        elif t == 'AUTH_UNWRAPPED':
            f = self._add_with_auth_unwrapped(self._base, parts)
        elif t == 'CERT':
            f = self._add_with_cert_auth(self._base, parts)
        else:
            # should never happen
            raise CloudFlareAPIError(0, 'api load type mismatch')

        if keyword.iskeyword(name):
            ## add the keyword appended with an extra underscore so it can used with Python code
            setattr(branch, name + '_', f)
        else:
            if '-' in name:
                # dashes (vs underscores) cause issues in Python and other languages
                setattr(branch, name.replace('-','_'), f)
            else:
                setattr(branch, name, f)

    def api_list(self):
        """recursive walk of the api tree returning a list of api calls"""
        return self._api_list(m=self)

    def _api_list(self, m=None, s=''):
        """recursive walk of the api tree returning a list of api calls"""
        w = []
        for n in sorted(dir(m)):
            if n[0] == '_':
                # internal
                continue
            if n in ['delete', 'get', 'patch', 'post', 'put']:
                # gone too far
                continue
            try:
                a = getattr(m, n)
            except AttributeError:
                # really should not happen!
                raise CloudFlareAPIError(0, '%s: not found - should not happen' % (n))
            d = dir(a)
            if '_base' in d:
                # it's a known api call - lets show the result and continue down the tree
                if 'delete' in d or 'get' in d or 'patch' in d or 'post' in d or 'put' in d:
                    # only show the result if a call exists for this part
                    if '_parts_unused' in d:
                            # This is an uncallable endpoint - presently no way to return this info
                            # w.append(str(a)[1:-1] + ' ; UNUSED')
                            pass
                    if '_parts' in d:
                        if n[-1] == '_':
                            if  keyword.iskeyword(n[:-1]):
                                # should always be a keyword - but now nothing needs to be done
                                pass
                            # remove the extra keyword postfix'ed with underscore
                            w.append(str(a)[1:-1])
                        else:
                            # handle underscores by returning the actual API call vs the method name
                            w.append(str(a)[1:-1])
                # now recurse downwards into the tree
                w = w + self._api_list(a, s + '/' + n)
        return w

    def api_from_web(self):
        """ Cloudflare v4 API"""

        return api_decode_from_web(self._base.api_from_web())

    def api_from_openapi(self, url):
        """ Cloudflare v4 API"""

        return api_decode_from_openapi(self._base.api_from_openapi(url))

    def __init__(self, email=None, key=None, token=None, certtoken=None, debug=False, raw=False, use_sessions=True, profile=None, base_url=None, global_request_timeout=5, max_request_retries=5):
        """ Cloudflare v4 API"""

        self._base = None

        try:
            config = read_configs(profile)
        except Exception as e:
            raise e

        # class creation values override all configuration values
        if email is not None:
            config['email'] = email
        if key is not None:
            config['key'] = key
        if token is not None:
            config['token'] = token
        if certtoken is not None:
            config['certtoken'] = certtoken
        if debug is not None:
            config['debug'] = debug
        if raw is not None:
            config['raw'] = raw
        if use_sessions is not None:
            config['use_sessions'] = use_sessions
        if profile is not None:
            config['profile'] = profile
        if base_url is not None:
            config['base_url'] = base_url
        if global_request_timeout is not None:
            config['global_request_timeout'] = global_request_timeout
        if max_request_retries is not None:
            config['max_request_retries'] = max_request_retries

        # we do not need to handle item.call values - they pass straight thru

        for x in config:
            if config[x] == '':
                config[x] = None

        self._base = self._v4base(config)

        # add the API calls
        try:
            api_v4(self)
            if 'extras' in config and config['extras']:
                api_extras(self, config['extras'])
        except Exception as e:
            raise e

    def __del__(self):
        """ Network for Cloudflare API"""

        if self._base:
            del self._base
            self._base = None

    def __call__(self):
        """ Cloudflare v4 API"""

        raise TypeError('object is not callable')

    def __enter__(self):
        """ Cloudflare v4 API"""
        return self

    def __exit__(self, t, v, tb):
        """ Cloudflare v4 API"""
        if t is None:
            return True
        # pretend we didn't deal with raised error - which is true
        return False

    def __str__(self):
        """ Cloudflare v4 API"""

        if self._base.api_email is None:
            s = '["%s","%s"]' % (self._base.profile, 'REDACTED')
        else:
            s = '["%s","%s","%s"]' % (self._base.profile, self._base.api_email, 'REDACTED')
        return s

    def __repr__(self):
        """ Cloudflare v4 API"""

        if self._base.api_email is None:
            s = '%s,%s("%s","%s","%s","%s",%s,"%s")' % (
                self.__module__, type(self).__name__,
                self._base.profile, 'REDACTED', 'REDACTED',
                self._base.base_url, self._base.raw, self._base.user_agent
            )
        else:
            s = '%s,%s("%s","%s","%s","%s","%s",%s,"%s")' % (
                self.__module__, type(self).__name__,
                self._base.profile, self._base.api_email, 'REDACTED', 'REDACTED',
                self._base.base_url, self._base.raw, self._base.user_agent
            )
        return s

    def __getattr__(self, key):
        """ __getattr__ """

        # this code will expand later
        if key in dir(self):
            return self[key]
        # this is call to a non-existent endpoint
        raise AttributeError(key)
