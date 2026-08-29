document.addEventListener(
    "DOMContentLoaded",
    function () {

        const body = document.body;
        const sidebarToggle = document.querySelector("[data-sidebar-toggle]");
        const sidebarClose = document.querySelector("[data-sidebar-close]");
        const sidebarLinks = document.querySelectorAll(".sidebar-link");

        function setSidebar(open) {
            body.classList.toggle("sidebar-open", open);

            if (sidebarToggle) {
                sidebarToggle.setAttribute("aria-expanded", String(open));
            }
        }

        if (sidebarToggle) {
            sidebarToggle.addEventListener("click", function () {
                setSidebar(!body.classList.contains("sidebar-open"));
            });
        }

        if (sidebarClose) {
            sidebarClose.addEventListener("click", function () {
                setSidebar(false);
            });
        }

        sidebarLinks.forEach(function (link) {
            link.addEventListener("click", function () {
                setSidebar(false);
            });
        });

        document.addEventListener("keydown", function (event) {
            if (event.key === "Escape") {
                setSidebar(false);
            }
        });

        window.addEventListener("resize", function () {
            if (window.innerWidth >= 992) {
                setSidebar(false);
            }
        });

        const alerts =
            document.querySelectorAll(
                ".alert-dismissible"
            );

        alerts.forEach(
            function (alert) {

                setTimeout(
                    function () {

                        if (window.bootstrap && window.bootstrap.Alert) {
                            const bsAlert =
                                window.bootstrap.Alert.getOrCreateInstance(
                                    alert
                                );

                            bsAlert.close();
                        }

                    },
                    3000
                );

            }
        );

    }
);
