from app.common.exceptions import DomainError


class MontageBusy(DomainError):
    pass


class MontageUnavailable(DomainError):
    pass


class BrandLogoRefused(DomainError):
    pass


class BrandFaceIncomplete(DomainError):
    pass
