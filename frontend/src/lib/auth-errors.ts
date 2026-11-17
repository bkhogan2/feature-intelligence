export class AuthConfigurationError extends Error {}
export class EmailVerificationRequiredError extends Error {
  constructor() {
    super(
      "Verify your email before continuing. You can resend the verification email below.",
    );
  }
}
