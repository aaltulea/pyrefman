from pyrefman.styles.VancouverStyle import VancouverStyle


class VancouverBoldTitleStyle(VancouverStyle):
    def describe_style(self) -> str:
        return "Vancouver-style numbered citations with bolded titles in the reference list."

    def get_title(self, inline_reference) -> str:
        output = super().get_title(inline_reference)
        return f"**{output}**"
