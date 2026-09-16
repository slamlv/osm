console.log("=== COMBOBOX.JS CHARGÉ ===");

function initComboboxes(root = document) {
    root.querySelectorAll("select.combobox").forEach((element) => {
        if (element.dataset.choicesInitialized === "true") {
            return;
        }

        new Choices(element, {
            searchEnabled: true,
            searchChoices: true,
            searchFields: ["label"],

            fuseOptions: {
                threshold: 0,
                ignoreLocation: true,
            },

            shouldSort: element.dataset.shouldSort === "true",

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
                element.dataset.searchPlaceholder || "Rechercher...",

            allowHTML: false,
        });

        element.dataset.choicesInitialized = "true";
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
