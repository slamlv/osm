from django import forms
from .widgets import ComboboxWidget


class ComboboxField(forms.ChoiceField):
    """ChoiceField avec recherche Choices.js."""

    def __init__(
        self,
        choices=(),
        *,
        attrs=None,
        choices_options=None,
        **kwargs,
    ):
        widget = kwargs.pop("widget", None)

        if widget is None:
            widget = ComboboxWidget(
                attrs=attrs,
                choices=choices,
                choices_options=choices_options,
            )

        super().__init__(
            choices=choices,
            widget=widget,
            **kwargs,
        )


class ModelComboboxField(forms.ModelChoiceField):
    """ModelChoiceField avec recherche Choices.js."""

    def __init__(
        self,
        queryset,
        *,
        attrs=None,
        choices_options=None,
        **kwargs,
    ):
        widget = kwargs.pop("widget", None)

        if widget is None:
            widget = ComboboxWidget(
                attrs=attrs,
                choices_options=choices_options,
            )

        super().__init__(
            queryset=queryset,
            widget=widget,
            **kwargs,
        )
