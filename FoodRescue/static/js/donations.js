document.addEventListener("DOMContentLoaded", function () {
    const searchInput = document.getElementById("donationSearch");
    const categorySelect = document.getElementById("donationCategory");
    const clearButton = document.getElementById("clearDonationFilters");
    const resultCount = document.getElementById("donationResultCount");
    const emptyState = document.getElementById("noDonationsFound");
    const donationItems = Array.from(document.querySelectorAll(".donation-item"));

    document.querySelectorAll(".donation-photo").forEach(function (image) {
        image.addEventListener("error", function () {
            image.hidden = true;
        });
    });

    function updateDonations() {
        const searchTerm = searchInput.value.trim().toLowerCase();
        const selectedCategory = categorySelect.value;
        let visibleCount = 0;

        donationItems.forEach(function (item) {
            const card = item.querySelector(".donation-card");
            const matchesSearch = card.textContent.toLowerCase().includes(searchTerm);
            const matchesCategory =
                selectedCategory === "all" || card.dataset.category === selectedCategory;
            const isVisible = matchesSearch && matchesCategory;

            item.classList.toggle("d-none", !isVisible);
            if (isVisible) {
                visibleCount += 1;
            }
        });

        resultCount.textContent =
            "Showing " + visibleCount + " donation" + (visibleCount === 1 ? "" : "s");
        emptyState.classList.toggle("d-none", visibleCount > 0);
    }

    searchInput.addEventListener("input", updateDonations);
    categorySelect.addEventListener("change", updateDonations);
    clearButton.addEventListener("click", function () {
        searchInput.value = "";
        categorySelect.value = "all";
        updateDonations();
        searchInput.focus();
    });

    document.querySelectorAll("[data-listing-details]").forEach(function (button) {
        button.addEventListener("click", function () {
            document.getElementById("donationModalTitle").textContent = button.dataset.title;
            document.getElementById("donationModalCategory").textContent = button.dataset.category;
            document.getElementById("donationModalDescription").textContent =
                button.dataset.description;
            document.getElementById("donationModalDonor").textContent = button.dataset.donor;
            document.getElementById("donationModalQuantity").textContent = button.dataset.quantity;
            document.getElementById("donationModalLocation").textContent = button.dataset.location;
            document.getElementById("donationModalPickup").textContent = button.dataset.pickup;
            document.getElementById("donationModalNote").textContent =
                button.dataset.sample === "1"
                    ? "This is a sample listing. It demonstrates the claim and pickup flow; no real food is available."
                    : "After claiming, you can contact the donor from your account dashboard.";
        });
    });

    updateDonations();
});
