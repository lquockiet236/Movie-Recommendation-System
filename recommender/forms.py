from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User


class SignUpForm(UserCreationForm):
    email = forms.EmailField(required=True)

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ('username', 'email', 'password1', 'password2')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        field_content = {
            'username': (
                'Tên đăng nhập',
                'Tên đăng nhập',
                'username',
                'Tối đa 150 ký tự; dùng chữ cái, chữ số và @/./+/-/_.',
            ),
            'email': ('Email', 'Địa chỉ email', 'email', ''),
            'password1': (
                'Mật khẩu',
                'Tạo mật khẩu',
                'new-password',
                'Tối thiểu 8 ký tự; không quá phổ biến, không chỉ gồm số và không quá giống thông tin cá nhân.',
            ),
            'password2': (
                'Nhập lại mật khẩu',
                'Nhập lại mật khẩu',
                'new-password',
                'Nhập chính xác mật khẩu ở trên để xác nhận.',
            ),
        }
        for field_name, (label, placeholder, autocomplete, help_text) in field_content.items():
            field = self.fields[field_name]
            field.label = label
            field.help_text = help_text
            field.widget.attrs.update({
                'placeholder': placeholder,
                'autocomplete': autocomplete,
            })

    def clean_email(self):
        email = self.cleaned_data['email'].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError('Email này đã được sử dụng.')
        return email
