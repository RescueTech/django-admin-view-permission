from __future__ import unicode_literals

from django.apps import apps
from django.conf import settings
from django.conf.urls import url
from django.contrib import admin
from django.utils.text import capfirst
from django.utils.encoding import force_text
from django.contrib.auth import get_permission_codename
from django.contrib.admin.utils import unquote, quote
from django.core.urlresolvers import NoReverseMatch, reverse
from django.core.exceptions import PermissionDenied
from django.contrib.admin.views.main import ChangeList
from django.utils.translation import ugettext as _

SETTINGS_MODELS = getattr(settings, 'ADMIN_VIEW_PERMISSION_MODELS', None)


class AdminViewPermissionChangeList(ChangeList):
    def __init__(self, *args, **kwargs):
        super(AdminViewPermissionChangeList, self).__init__(*args, **kwargs)
        # TODO: Exam if is None
        self.request = args[0]

        # If user has only view permission change the title of the changelist
        # view
        if self.model_admin.has_view_permission(self.request) and \
                not self.model_admin.has_change_permission(self.request,
                                                           only_change=True):
            if self.is_popup:
                title = _('Select %s')
            else:
                title = _('Select %s to view')
            self.title = title % force_text(self.opts.verbose_name)


class AdminViewPermissionInlineModelAdmin(admin.options.InlineModelAdmin):
    def get_queryset(self, request):
        """
        Returns a QuerySet of all model instances that can be edited by the
        admin site. This is used by changelist_view.
        """
        qs = self.model._default_manager.get_queryset()
        # TODO: this should be handled by some parameter to the ChangeList.
        ordering = self.get_ordering(request)
        if ordering:
            qs = qs.order_by(*ordering)
        return qs

    def get_fields(self, request, obj=None):
        fields = super(AdminViewPermissionInlineModelAdmin, self).get_fields(
            request, obj)
        readonly_fields = self.get_readonly_fields(request, obj)
        return [i for i in fields if i in readonly_fields]

    def get_readonly_fields(self, request, obj=None):
        """
        Return all fields as readonly for the view permission
        """
        local_fields = [field.name for field in self.opts.local_fields]
        many_to_many_fields = [field.name for field in
                               self.opts.local_many_to_many]
        all_fields = local_fields + many_to_many_fields
        if self.fields:
            defined_admin_fields = [field for field in self.fields if
                                    field not in all_fields]
            all_fields += defined_admin_fields
        return list(all_fields)


class AdminViewPermissionModelAdmin(admin.ModelAdmin):
    def get_changelist(self, request, **kwargs):
        """
        Returns the ChangeList class for use on the changelist page.
        """
        return AdminViewPermissionChangeList

    def get_model_perms(self, request):
        """
        Returns a dict of all perms for this model. This dict has the keys
        ``add``, ``change``, ``delete`` and ``view`` mapping to the True/False
        for each of those actions.
        """
        return {
            'add': self.has_add_permission(request),
            'change': self.has_change_permission(request),
            'delete': self.has_delete_permission(request),
            'view': self.has_view_permission(request)
        }

    def has_view_permission(self, request, obj=None):
        """
        Returns True if the given request has permission to view an object.
        Can be overridden by the user in subclasses.
        """
        opts = self.opts
        codename = get_permission_codename('view', opts)
        return request.user.has_perm("%s.%s" % (opts.app_label, codename))

    def has_change_permission(self, request, obj=None, only_change=False):
        """
        Override this method in order to return True whenever a user has view
        permission and avoid re-implementing the change_view and
        changelist_view views. Also, added an extra argument to determine
        whenever this function will return the original response
        """
        change_permission = super(AdminViewPermissionModelAdmin,
                                  self).has_change_permission(request, obj)
        if only_change:
            return change_permission
        else:
            if change_permission or self.has_view_permission(request, obj):
                return True
            else:
                return change_permission

    def get_fields(self, request, obj=None):
        """
        If the user has only the view permission return these readonly fields
        which are in fields attr
        """
        if self.has_view_permission(request, obj) and \
                not self.has_change_permission(request, obj, True):
            fields = super(AdminViewPermissionModelAdmin, self).get_fields(
                request, obj)
            readonly_fields = self.get_readonly_fields(request, obj)
            new_fields = [i for i in fields if i in readonly_fields]
            return new_fields
        else:
            return super(AdminViewPermissionModelAdmin, self).get_fields(
                request, obj)

    def get_readonly_fields(self, request, obj=None):
        """
        Return all fields as readonly for the view permission
        """
        if self.has_view_permission(request, obj) and \
                not self.has_change_permission(request, obj, True):
            readonly_fields = list(
                [field.name for field in self.opts.local_fields] +
                [field.name for field in self.opts.local_many_to_many]
            )
            try:
                readonly_fields.remove('id')
                return tuple(readonly_fields)
            except ValueError:
                pass
        else:
            return super(AdminViewPermissionModelAdmin,
                         self).get_readonly_fields(request, obj)

    def get_actions(self, request):
        """
        Override this funciton to remove the actions from the changelist view
        """
        if self.has_view_permission(request) and \
                not self.has_change_permission(request, only_change=True):
            return None
        else:
            return super(AdminViewPermissionModelAdmin, self).get_actions(
                request)

    def get_inline_instances(self, request, obj=None):
        inline_instances = []
        for inline_class in self.inlines:
            if self.has_view_permission(request) and \
                    not self.has_change_permission(request, only_change=True):

                inline_class.can_delete = False
                inline_class.max_num = 0
                inline_class.extra = 2
                new_class = type(
                    str('DynamicAdminViewPermissionInlineModelAdmin'),
                    (inline_class, AdminViewPermissionInlineModelAdmin),
                    dict(inline_class.__dict__))
                inline = new_class(self.model, self.admin_site)
            else:
                inline = inline_class(self.model, self.admin_site)
            inline_instances.append(inline)

        return inline_instances

    def change_view(self, request, object_id, form_url='', extra_context=None):
        """
        Override this function to hide the sumbit row from the user who has
        view only permission
        """
        model = self.model
        opts = model._meta

        if object_id:
            obj = None
        else:
            obj = self.get_object(request, unquote(object_id))

        if self.has_view_permission(request, obj) and \
                not self.has_change_permission(request, obj, True):
            extra_context = extra_context or {}
            extra_context['title'] = _('View %s') % force_text(
                opts.verbose_name)
            extra_context['show_save'] = False
            extra_context['show_save_and_continue'] = False

        return super(AdminViewPermissionModelAdmin, self).change_view(request,
                                                                      object_id,
                                                                      form_url,
                                                                      extra_context)


class AdminViewPermissionAdminSite(admin.AdminSite):
    def register(self, model_or_iterable, admin_class=None, **options):
        """
        Create a new ModelAdmin class which inherits from the original and the above and register
        all models with that
        """
        models = model_or_iterable
        if not isinstance(model_or_iterable, tuple):
            models = tuple([model_or_iterable])

        if SETTINGS_MODELS or \
                (isinstance(SETTINGS_MODELS, list or tuple) and len(
                    SETTINGS_MODELS) == 0):
            for model in models:
                if model._meta.label in SETTINGS_MODELS:
                    if admin_class:
                        admin_class = type(
                            str('DynamicAdminViewPermissionModelAdmin'),
                            (admin_class, AdminViewPermissionModelAdmin),
                            dict(admin_class.__dict__))
                    else:
                        admin_class = AdminViewPermissionModelAdmin

                super(AdminViewPermissionAdminSite, self).register(model,
                                                                   admin_class,
                                                                   **options)
        else:
            if admin_class:
                admin_class = type(str('DynamicAdminViewPermissionModelAdmin'),
                                   (
                                   admin_class, AdminViewPermissionModelAdmin),
                                   dict(admin_class.__dict__))
            else:
                admin_class = AdminViewPermissionModelAdmin

            super(AdminViewPermissionAdminSite, self).register(
                model_or_iterable,
                admin_class, **options)

    def _build_app_dict(self, request, label=None):
        """
        Builds the app dictionary. Takes an optional label parameters to filter
        models of a specific app.
        """
        app_dict = {}

        if label:
            models = {
                m: m_a for m, m_a in self._registry.items()
                if m._meta.app_label == label
                }
        else:
            models = self._registry

        for model, model_admin in models.items():
            app_label = model._meta.app_label

            has_module_perms = model_admin.has_module_permission(request)
            if not has_module_perms:
                if label:
                    raise PermissionDenied
                continue

            perms = model_admin.get_model_perms(request)

            # Check whether user has any perm for this module.
            # If so, add the module to the model_list.
            if True not in perms.values():
                continue

            info = (app_label, model._meta.model_name)
            model_dict = {
                'name': capfirst(model._meta.verbose_name_plural),
                'object_name': model._meta.object_name,
                'perms': perms,
            }
            if perms.get('change') or perms.get('view'):
                try:
                    model_dict['admin_url'] = reverse(
                        'admin:%s_%s_changelist' % info, current_app=self.name)
                except NoReverseMatch:
                    pass
            if perms.get('add'):
                try:
                    model_dict['add_url'] = reverse('admin:%s_%s_add' % info,
                                                    current_app=self.name)
                except NoReverseMatch:
                    pass

            if app_label in app_dict:
                app_dict[app_label]['models'].append(model_dict)
            else:
                app_dict[app_label] = {
                    'name': apps.get_app_config(app_label).verbose_name,
                    'app_label': app_label,
                    'app_url': reverse(
                        'admin:app_list',
                        kwargs={'app_label': app_label},
                        current_app=self.name,
                    ),
                    'has_module_perms': has_module_perms,
                    'models': [model_dict],
                }

        if label:
            return app_dict.get(label)

        return app_dict
