console.log("=== COMBOBOX.JS CHARGÉ ===");

function initComboboxes(root = document) {
    const elements = root.querySelectorAll("select.combobox");

    elements.forEach((element) => {
        if (element.dataset.choicesInitialized === "true") {
            return;
        }

        const optionsElement = document.getElementById(
            `${element.id}-choices-options`
        );

        let options = {};

        if (optionsElement) {
            try {
                options = JSON.parse(optionsElement.textContent);
            } catch (error) {
                console.error(
                    "Impossible de lire les options Choices.js :",
                    error
                );
            }
        }

        const defaultOptions = {
            searchEnabled: true,
            searchChoices: true,

            /* Recherche UNIQUEMENT dans le label visible. */
            searchFields: ["label"],

            shouldSort: false,
            itemSelectText: "",

            noResultsText:
                element.dataset.noResultsText || "Aucun résultat",

            noChoicesText:
                element.dataset.noChoicesText ||
                "Aucune option disponible",

            placeholder: true,

            placeholderValue:
                element.dataset.placeholder || "Sélectionner...",

            searchPlaceholderValue:
                element.dataset.searchPlaceholder ||
                "Rechercher...",

            allowHTML: false,
        };

        const finalOptions = {
            ...defaultOptions,
            ...options,
            searchFields: ["label"],
        };

        try {
            const choices = new Choices(element, finalOptions);

            // On conserve l'instance pour permettre aux autres scripts
            // d'ajouter/sélectionner une option via l'API Choices.
            element._choices = choices;

            // Ne pas recopier les classes Bootstrap du <select>
            // vers les éléments internes de Choices.js.
            // Cela évite notamment qu'une classe comme bg-light
            // modifie l'apparence du champ principal.
            if (element.classList.contains("fw-bold")) {
                choices.containerInner?.element.classList.add("fw-bold");
            }

            element.dataset.choicesInitialized = "true";
        } catch (error) {
            console.error(
                "Erreur lors de l'initialisation du combobox :",
                error
            );
        }
    });
}

if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => {
        initComboboxes();
    });
} else {
    initComboboxes();
}

document.addEventListener("htmx:afterSwap", (event) => {
    initComboboxes(event.target);
});
