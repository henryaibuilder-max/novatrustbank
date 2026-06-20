from allauth.account.adapter import DefaultAccountAdapter


class BankAccountAdapter(DefaultAccountAdapter):
    def is_open_for_signup(self, request):
        return True

    def get_login_redirect_url(self, request):
        return '/dashboard/'

    def get_signup_redirect_url(self, request):
        return '/dashboard/'
