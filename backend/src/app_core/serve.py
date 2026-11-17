"""Provider-independent container entry point, including Cloud Run's PORT convention."""

import os
import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "app_core.main:create_app",
        factory=True,
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8080")),
    )
