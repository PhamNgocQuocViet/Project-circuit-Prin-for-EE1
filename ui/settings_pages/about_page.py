"""About page for the settings dialog."""

from PyQt5.QtWidgets import QLabel, QVBoxLayout, QWidget


PROJECT_MEMBERS = [
    "Phạm Ngọc Quốc Việt - EEEESB24010",
    "Nguyên Anh Quân - EEACIU25049",
    "Ngô Phan Minh Quân - EEACIU25050",
    "Nguyên Lê Minh Quân - EEACIU25051",
    "Hoàng Bá Minh Quân - EEACIU25052",
]

COPYRIGHT_NOTICE = "Copyright 2026 " + "; ".join(PROJECT_MEMBERS)
LICENSE_NOTICE = (
    "Distributed free of charge under the CircuitSolver Source-Available Freeware License. "
    "Sale or redistribution requires prior written permission from the copyright holders."
)


class AboutPage(QWidget):
    """Application information page."""

    def __init__(self, parent=None):
        """Build the read-only project and contributor information page."""
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        title = QLabel("About")
        title.setProperty("role", "pageTitle")
        layout.addWidget(title)

        card = QWidget()
        card.setProperty("role", "settingsCard")
        card_layout = QVBoxLayout(card)

        app_name = QLabel("Electrical Engineering Learning App")
        app_name.setProperty("role", "sectionTitle")
        card_layout.addWidget(app_name)

        description = QLabel(
            "A desktop circuit practice tool for placing components, assigning values, "
            "and generating AI-assisted solving prompts."
        )
        description.setWordWrap(True)
        description.setProperty("role", "mutedText")
        card_layout.addWidget(description)

        members_title = QLabel("Project Members")
        members_title.setProperty("role", "sectionTitle")
        card_layout.addWidget(members_title)

        members = QLabel("\n".join(PROJECT_MEMBERS))
        members.setWordWrap(True)
        members.setProperty("role", "mutedText")
        card_layout.addWidget(members)

        affiliation = QLabel("HCMIU, Vietnam National University")
        affiliation.setWordWrap(True)
        affiliation.setProperty("role", "mutedText")
        card_layout.addWidget(affiliation)

        copyright_label = QLabel(COPYRIGHT_NOTICE)
        copyright_label.setWordWrap(True)
        copyright_label.setProperty("role", "mutedText")
        card_layout.addWidget(copyright_label)

        license_label = QLabel(LICENSE_NOTICE)
        license_label.setWordWrap(True)
        license_label.setProperty("role", "mutedText")
        card_layout.addWidget(license_label)

        layout.addWidget(card)
        layout.addStretch(1)

    def apply_settings(self):
        """Provide the common page hook; the About page has nothing to save."""
        return
