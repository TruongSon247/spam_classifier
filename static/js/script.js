document.addEventListener(
    "DOMContentLoaded",
    function () {

        const alerts =
            document.querySelectorAll(
                ".alert-dismissible"
            );

        alerts.forEach(
            function (alert) {

                setTimeout(
                    function () {

                        const bsAlert =
                            bootstrap.Alert.getOrCreateInstance(
                                alert
                            );

                        bsAlert.close();

                    },
                    3000
                );

            }
        );

    }
);