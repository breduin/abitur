from django import forms
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from .models import User


class LoginForm(forms.Form):
    abiturient_id = forms.CharField(
        label="ID абитуриента",
        max_length=32,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Введите ваш ID"}),
    )


@require_http_methods(["GET", "POST"])
def login_view(request):
    if request.user.is_authenticated:
        return redirect("dashboard")

    message = None
    if request.method == "POST":
        form = LoginForm(request.POST)
        if form.is_valid():
            abiturient_id = form.cleaned_data["abiturient_id"].strip()
            user = authenticate(request, abiturient_id=abiturient_id)
            if user:
                login(request, user, backend="apps.users.backends.AbiturientIDBackend")
                return redirect("dashboard")

            try:
                existing = User.objects.get(abiturient_id=abiturient_id)
                if not existing.is_verified:
                    message = "Ожидайте верификации администратором."
            except User.DoesNotExist:
                User.objects.create_user(abiturient_id=abiturient_id)
                message = "Заявка отправлена. Ожидайте верификации администратором."
    else:
        form = LoginForm()

    return render(request, "users/login.html", {"form": form, "message": message})


@require_http_methods(["POST", "GET"])
def logout_view(request):
    logout(request)
    return redirect("login")


class CabinetForm(forms.ModelForm):
    applied_universities = forms.ModelMultipleChoiceField(
        queryset=None,
        widget=forms.CheckboxSelectMultiple,
        required=False,
        label="Медицинский университет с поданными заявлениями",
    )

    class Meta:
        model = User
        fields = ("ege_total_score", "has_honors_diploma", "applied_universities")
        widgets = {
            "ege_total_score": forms.NumberInput(attrs={"class": "form-control", "min": 0, "max": 400}),
            "has_honors_diploma": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.universities.models import MedicalUniversity

        self.fields["applied_universities"].queryset = MedicalUniversity.objects.filter(is_active=True)


@login_required
@require_http_methods(["GET", "POST"])
def cabinet_view(request):
    if request.method == "POST":
        form = CabinetForm(request.POST, instance=request.user)
        if form.is_valid():
            form.save()
            return redirect("cabinet")
    else:
        form = CabinetForm(instance=request.user)

    return render(request, "users/cabinet.html", {"form": form})
