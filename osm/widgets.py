from django import forms
from django.utils.html import json_script


class ComboboxWidget(forms.Select):
    template_name = "combobox.html"

    class Media:
        css = {
            "all": (
                "choices.min.css",
                "combobox.css",
            ),
        }

        js = (
            "choices.min.js",
            "combobox.js",
        )

    DEFAULT_CHOICES_OPTIONS = {
        "searchEnabled": True,
        "searchChoices": True,

        # Recherche uniquement dans le label visible de l'option.
        "searchFields": ["label"],

        "shouldSort": False,
        "itemSelectText": "",
        "noResultsText": "Aucun résultat",
        "noChoicesText": "Aucune option disponible",
        "placeholder": True,
        "allowHTML": False,
    }

    def __init__(
        self,
        attrs=None,
        choices=(),
        *,
        choices_options=None,
    ):
        # Ne jamais modifier le dictionnaire attrs fourni par l'appelant.
        attrs = attrs.copy() if attrs else {}

        classes = attrs.get("class", "")
        attrs["class"] = f"{classes} combobox".strip()

        self.choices_options = self.DEFAULT_CHOICES_OPTIONS.copy()

        if choices_options:
            self.choices_options.update(choices_options)

        super().__init__(
            attrs=attrs,
            choices=choices,
        )

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)

        widget = context["widget"]
        widget["choices_options"] = self.choices_options

        widget_id = widget["attrs"].get("id")

        if widget_id:
            options_id = f"{widget_id}-choices-options"

            # IMPORTANT :
            # On utilise la fonction Python json_script() plutôt que
            # le filtre Django avec un argument dynamique.
            #
            # Le filtre :
            #   {{ value|json_script:widget.choices_options_id }}
            #
            # ne permet PAS de passer une variable après ":" comme on
            # pourrait le penser : l'argument est interprété comme une
            # chaîne littérale.
            widget["choices_options_json"] = json_script(
                self.choices_options,
                options_id,
            )

            widget["choices_options_id"] = options_id

        return context
