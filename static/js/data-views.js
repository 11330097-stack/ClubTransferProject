(function () {
    'use strict';

    function setupSelectionToolbar(toolbar) {
        var checkboxSelector = toolbar.dataset.selectionCheckbox;
        var masterSelector = toolbar.dataset.selectionMaster;
        if (!checkboxSelector) {
            return;
        }

        var checkboxes = Array.from(document.querySelectorAll(checkboxSelector));
        var master = masterSelector ? document.querySelector(masterSelector) : null;
        var count = toolbar.querySelector('[data-selected-count]');

        function update() {
            var selected = checkboxes.filter(function (checkbox) {
                return checkbox.checked;
            });
            checkboxes.forEach(function (checkbox) {
                var row = checkbox.closest('tr');
                if (row) {
                    row.classList.toggle('is-selected', checkbox.checked);
                }
            });
            if (count) {
                count.textContent = selected.length;
            }
            if (master) {
                master.checked = checkboxes.length > 0 && selected.length === checkboxes.length;
                master.indeterminate = selected.length > 0 && selected.length < checkboxes.length;
            }
        }

        function setAll(checked) {
            checkboxes.forEach(function (checkbox) {
                checkbox.checked = checked;
            });
            update();
        }

        checkboxes.forEach(function (checkbox) {
            checkbox.addEventListener('change', update);
        });
        if (master) {
            master.addEventListener('change', function () {
                setAll(master.checked);
            });
        }
        toolbar.querySelectorAll('[data-select-all]').forEach(function (button) {
            button.addEventListener('click', function () {
                setAll(true);
            });
        });
        toolbar.querySelectorAll('[data-clear-selection]').forEach(function (button) {
            button.addEventListener('click', function () {
                setAll(false);
            });
        });
        update();
    }

    document.addEventListener('DOMContentLoaded', function () {
        document.querySelectorAll('[data-selection-checkbox]').forEach(setupSelectionToolbar);
    });
}());
