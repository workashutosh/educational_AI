from django import forms

from .models import SchoolMembership


class LoginForm(forms.Form):
    username = forms.CharField(max_length=150, widget=forms.TextInput(attrs={
        "autocomplete": "username",
        "placeholder": "Username",
    }))
    password = forms.CharField(widget=forms.PasswordInput(attrs={
        "autocomplete": "current-password",
        "placeholder": "Password",
    }))


class SchoolOnboardForm(forms.Form):
    school_name = forms.CharField(
        max_length=255,
        label="School name",
        widget=forms.TextInput(attrs={"placeholder": "e.g. Greenfield High"}),
    )
    full_name = forms.CharField(
        max_length=150,
        required=False,
        label="Your name",
        widget=forms.TextInput(attrs={"placeholder": "Optional"}),
    )
    username = forms.CharField(max_length=150, widget=forms.TextInput(attrs={
        "autocomplete": "username",
        "placeholder": "Admin username",
    }))
    email = forms.EmailField(widget=forms.EmailInput(attrs={
        "autocomplete": "email",
        "placeholder": "you@school.edu",
    }))
    password = forms.CharField(
        min_length=8,
        widget=forms.PasswordInput(attrs={
            "autocomplete": "new-password",
            "placeholder": "Min. 8 characters",
        }),
    )
    password_confirm = forms.CharField(
        label="Confirm password",
        widget=forms.PasswordInput(attrs={
            "autocomplete": "new-password",
            "placeholder": "Repeat password",
        }),
    )

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("password") != cleaned.get("password_confirm"):
            self.add_error("password_confirm", "Passwords do not match.")
        return cleaned


class JoinSchoolForm(forms.Form):
    join_code = forms.CharField(
        max_length=12,
        label="School join code",
        widget=forms.TextInput(attrs={
            "placeholder": "8-character code from your admin",
            "style": "text-transform:uppercase",
        }),
    )
    role = forms.ChoiceField(
        choices=[
            (SchoolMembership.ROLE_TEACHER, "Teacher"),
            (SchoolMembership.ROLE_STUDENT, "Student"),
        ],
        initial=SchoolMembership.ROLE_TEACHER,
    )
    full_name = forms.CharField(
        max_length=150,
        required=False,
        label="Your name",
        widget=forms.TextInput(attrs={"placeholder": "Optional"}),
    )
    username = forms.CharField(max_length=150, widget=forms.TextInput(attrs={
        "autocomplete": "username",
        "placeholder": "Choose a username",
    }))
    email = forms.EmailField(widget=forms.EmailInput(attrs={
        "autocomplete": "email",
        "placeholder": "you@school.edu",
    }))
    password = forms.CharField(
        min_length=8,
        widget=forms.PasswordInput(attrs={
            "autocomplete": "new-password",
            "placeholder": "Min. 8 characters",
        }),
    )
    password_confirm = forms.CharField(
        label="Confirm password",
        widget=forms.PasswordInput(attrs={
            "autocomplete": "new-password",
            "placeholder": "Repeat password",
        }),
    )

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("password") != cleaned.get("password_confirm"):
            self.add_error("password_confirm", "Passwords do not match.")
        return cleaned
