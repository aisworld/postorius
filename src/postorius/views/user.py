# -*- coding: utf-8 -*-
# Copyright (C) 1998-2016 by the Free Software Foundation, Inc.
#
# This file is part of Postorius.
#
# Postorius is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version.
#
# Postorius is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
# FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for
# more details.
#
# You should have received a copy of the GNU General Public License along with
# Postorius.  If not, see <http://www.gnu.org/licenses/>.

from __future__ import absolute_import, unicode_literals

import logging
from django.utils.six.moves.urllib.error import HTTPError

from allauth.account.models import EmailAddress
from django.forms import formset_factory
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.utils.decorators import method_decorator
from django.utils.translation import gettext as _
from django.http import Http404

from postorius import utils
from postorius.models import (
    MailmanApiError, List, MailmanUser, Mailman404Error)
from postorius.forms import UserPreferences, ChangeSubscriptionForm
from postorius.views.generic import MailmanUserView


logger = logging.getLogger(__name__)


class UserMailmanSettingsView(MailmanUserView):
    """The logged-in user's global Mailman Preferences."""

    @method_decorator(login_required)
    def post(self, request):
        try:
            mm_user = MailmanUser.objects.get(address=request.user.email)
            form = UserPreferences(request.POST)
            if form.is_valid():
                preferences = mm_user.preferences
                for key in form.fields.keys():
                    if form.cleaned_data[key] is not None:
                        # None: nothing set yet. Remember to remove this test
                        # when Mailman accepts None as a "reset to default"
                        # value.
                        preferences[key] = form.cleaned_data[key]
                preferences.save()
                messages.success(request,
                                 _('Your preferences have been updated.'))
            else:
                messages.error(request, _('Something went wrong.'))
        except MailmanApiError:
            return utils.render_api_error(request)
        except Mailman404Error as e:
            messages.error(request, e.msg)
        return redirect("user_mailmansettings")

    @method_decorator(login_required)
    def get(self, request):
        try:
            mm_user = MailmanUser.objects.get_or_create_from_django(
                request.user)
        except MailmanApiError:
            return utils.render_api_error(request)
        settingsform = UserPreferences(initial=mm_user.preferences)
        return render(request, 'postorius/user/mailman_settings.html',
                      {'mm_user': mm_user, 'settingsform': settingsform})


class UserAddressPreferencesView(MailmanUserView):
    """The logged-in user's address-based Mailman Preferences."""

    @method_decorator(login_required)
    def post(self, request):
        try:
            mm_user = MailmanUser.objects.get(address=request.user.email)
            formset_class = formset_factory(UserPreferences)
            formset = formset_class(request.POST)
            if formset.is_valid():
                for form, address in zip(formset.forms, mm_user.addresses):
                    preferences = address.preferences
                    for key in form.fields.keys():
                        if (key in form.cleaned_data and
                           form.cleaned_data[key] is not None):
                            # None: nothing set yet. Remember to remove this
                            # test when Mailman accepts None as a
                            # "reset to default" value.
                            preferences[key] = form.cleaned_data[key]
                    preferences.save()
                messages.success(request,
                                 _('Your preferences have been updated.'))
            else:
                messages.error(request, _('Something went wrong.'))
        except MailmanApiError:
            return utils.render_api_error(request)
        except HTTPError as e:
            messages.error(request, e.msg)
        return redirect("user_address_preferences")

    @method_decorator(login_required)
    def get(self, request):
        try:
            helperform = UserPreferences()
            mm_user = MailmanUser.objects.get(address=request.user.email)
            addresses = mm_user.addresses
            AFormset = formset_factory(UserPreferences, extra=len(addresses))
            formset = AFormset()
            zipped_data = zip(formset.forms, addresses)
            for form, address in zipped_data:
                form.initial = address.preferences
        except MailmanApiError:
            return utils.render_api_error(request)
        except Mailman404Error:
            return render(request, 'postorius/user/address_preferences.html',
                          {'nolists': 'true'})
        return render(request, 'postorius/user/address_preferences.html',
                      {'mm_user': mm_user, 'addresses': addresses,
                       'helperform': helperform, 'formset': formset,
                       'zipped_data': zipped_data})


@login_required
def user_list_options(request, list_id):
    mlist = List.objects.get_or_404(fqdn_listname=list_id)
    mm_user = MailmanUser.objects.get(address=request.user.email)
    subscription = None
    for s in mm_user.subscriptions:
        if s.role == 'member' and s.list_id == list_id:
            subscription = s
            break
    if not subscription:
        raise Http404(_('Subscription does not exist'))
    preferences = subscription.preferences
    if request.method == 'POST':
        form = UserPreferences(request.POST)
        if form.is_valid():
            for key in form.cleaned_data.keys():
                if form.cleaned_data[key] is not None:
                    # None: nothing set yet. Remember to remove this test
                    # when Mailman accepts None as a "reset to default"
                    # value.
                    preferences[key] = form.cleaned_data[key]
            preferences.save()
            messages.success(request, _('Your preferences have been updated.'))
            return redirect('user_list_options', list_id)
        else:
            messages.error(request, _('Something went wrong.'))
    else:
        form = UserPreferences(initial=subscription.preferences)
    user_emails = EmailAddress.objects.filter(
        user=request.user, verified=True).order_by(
        "email").values_list("email", flat=True)
    subscription_form = ChangeSubscriptionForm(
        user_emails, initial={'email': subscription.email})
    return render(request, 'postorius/user/list_options.html',
                  {'form': form, 'list': mlist,
                   'change_subscription_form': subscription_form})


class UserSubscriptionPreferencesView(MailmanUserView):
    """The logged-in user's subscription-based Mailman Preferences."""

    @method_decorator(login_required)
    def post(self, request):
        try:
            subscriptions = self._get_memberships()
            formset_class = formset_factory(UserPreferences)
            formset = formset_class(request.POST)
            if formset.is_valid():
                for form, subscription in zip(formset.forms, subscriptions):
                    preferences = subscription.preferences
                    for key in form.cleaned_data.keys():
                        if form.cleaned_data[key] is not None:
                            # None: nothing set yet. Remember to remove this
                            # test when Mailman accepts None as a
                            # "reset to default" value.
                            preferences[key] = form.cleaned_data[key]
                    preferences.save()
                messages.success(request,
                                 _('Your preferences have been updated.'))
            else:
                messages.error(request, _('Something went wrong.'))
        except MailmanApiError:
            return utils.render_api_error(request)
        except HTTPError as e:
            messages.error(request, e.msg)
        return redirect("user_subscription_preferences")

    @method_decorator(login_required)
    def get(self, request):
        try:
            subscriptions = self._get_memberships()
            Mformset = formset_factory(
                UserPreferences, extra=len(subscriptions))
            formset = Mformset()
            zipped_data = zip(formset.forms, subscriptions)
            for form, subscription in zipped_data:
                form.initial = subscription.preferences
        except MailmanApiError:
            return utils.render_api_error(request)
        except Mailman404Error:
            return render(request,
                          'postorius/user/subscription_preferences.html',
                          {'nolists': 'true'})
        return render(request, 'postorius/user/subscription_preferences.html',
                      {'zipped_data': zipped_data, 'formset': formset})


@login_required
def user_subscriptions(request):
    """Shows the subscriptions of a user."""
    try:
        mm_user = MailmanUser.objects.get_or_create_from_django(request.user)
    except MailmanApiError:
        return utils.render_api_error(request)
    memberships = [m for m in mm_user.subscriptions if m.role == 'member']
    return render(request, 'postorius/user/subscriptions.html',
                  {'memberships': memberships})
