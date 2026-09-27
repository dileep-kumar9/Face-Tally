import {
    initializeApp,
    getApps
} from "https://www.gstatic.com/firebasejs/12.17.1/firebase-app.js";

import {
    getAuth,
    onAuthStateChanged,
    signInWithEmailAndPassword,
    createUserWithEmailAndPassword,
    signInWithPopup,
    GoogleAuthProvider,
    sendPasswordResetEmail,
    signOut
} from "https://www.gstatic.com/firebasejs/12.17.1/firebase-auth.js";


let auth = null;
let firebaseReady = false;


// ============================================================
// FIREBASE INITIALIZATION
// ============================================================

async function loadFirebase() {

    const response =
        await fetch(
            "/firebase-config",
            {
                cache: "no-store",
                credentials: "same-origin"
            }
        );


    if (!response.ok) {
        throw new Error(
            "Could not load Firebase configuration."
        );
    }


    const config =
        await response.json();


    if (
        !config.apiKey ||
        !config.authDomain ||
        !config.projectId ||
        !config.appId
    ) {

        throw new Error(
            "Firebase web configuration is missing on the server."
        );
    }


    const app =
        getApps().length
            ? getApps()[0]
            : initializeApp(config);


    auth =
        getAuth(app);


    firebaseReady =
        true;


    window.FaceTallyAuth = {
        auth: auth,
        signOut: signOut,
        syncServerSession: syncServerSession
    };


    window.dispatchEvent(
        new CustomEvent(
            "facetally-auth-ready",
            {
                detail: {
                    auth: auth
                }
            }
        )
    );


    onAuthStateChanged(
        auth,
        async function (user) {

            if (
                user &&
                !user.isAnonymous
            ) {

                try {

                    await syncServerSession(
                        user
                    );

                } catch (error) {

                    console.warn(
                        "Could not sync Firebase session:",
                        error
                    );
                }
            }


            window.dispatchEvent(
                new CustomEvent(
                    "facetally-auth-state",
                    {
                        detail: {
                            user: user
                        }
                    }
                )
            );
        }
    );
}


// ============================================================
// SYNC FIREBASE USER WITH FLASK SESSION
// ============================================================

async function syncServerSession(user) {

    if (
        !user ||
        user.isAnonymous
    ) {
        return false;
    }


    const idToken =
        await user.getIdToken();


    const response =
        await fetch(
            "/auth/session",
            {
                method: "POST",

                headers: {
                    "Content-Type":
                        "application/json"
                },

                credentials:
                    "same-origin",

                body:
                    JSON.stringify(
                        {
                            idToken:
                                idToken
                        }
                    )
            }
        );


    const data =
        await response
            .json()
            .catch(
                function () {
                    return {};
                }
            );


    if (
        !response.ok ||
        !data.ok
    ) {

        throw new Error(
            data.error ||
            "Authentication failed."
        );
    }


    return true;
}


// ============================================================
// FIREBASE ERROR MESSAGES
// ============================================================

function authErrorMessage(error) {

    const code =
        error?.code || "";


    const messages = {

        "auth/invalid-credential":
            "Incorrect email or password.",

        "auth/invalid-email":
            "Enter a valid email address.",

        "auth/email-already-in-use":
            "An account already exists with this email.",

        "auth/weak-password":
            "Use a stronger password (at least 6 characters).",

        "auth/popup-closed-by-user":
            "Google sign-in was cancelled.",

        "auth/popup-blocked":
            "The Google sign-in popup was blocked. Allow popups and try again.",

        "auth/too-many-requests":
            "Too many attempts. Please wait and try again.",

        "auth/user-disabled":
            "This account has been disabled.",

        "auth/network-request-failed":
            "Network error. Check your internet connection and try again.",

        "auth/operation-not-allowed":
            "This sign-in method is not enabled in Firebase."
    };


    return (
        messages[code] ||
        error?.message ||
        "Authentication failed. Please try again."
    );
}


// ============================================================
// STATUS MESSAGE
// ============================================================

function setStatus(
    text,
    type = "error"
) {

    const status =
        document.getElementById(
            "auth-status"
        );


    if (!status) {
        return;
    }


    status.textContent =
        text;


    status.className =
        `auth-status ${type}`;


    status.hidden =
        !text;
}


// ============================================================
// COMPLETE LOGIN
// ============================================================

async function completeLogin(user) {

    await syncServerSession(
        user
    );


    const next =
        new URLSearchParams(
            window.location.search
        ).get("next");


    const destination =
        next &&
        next.startsWith("/") &&
        !next.startsWith("//")
            ? next
            : "/";


    window.location.href =
        destination;
}


// ============================================================
// GOOGLE LOGIN
// ============================================================

async function googleLogin() {

    if (!auth) {

        throw new Error(
            "Firebase is not ready yet."
        );
    }


    const provider =
        new GoogleAuthProvider();


    try {

        const result =
            await signInWithPopup(
                auth,
                provider
            );


        await completeLogin(
            result.user
        );

    } catch (error) {

        if (
            error?.code ===
            "auth/popup-blocked"
        ) {

            setStatus(
                "Google popup was blocked. Please allow popups for FaceTally and try again."
            );

            return;
        }


        throw error;
    }
}


// ============================================================
// AUTH PAGE
// ============================================================

async function wireAuthPage() {

    const form =
        document.getElementById(
            "auth-form"
        );


    const googleButton =
        document.getElementById(
            "google-signin-btn"
        );


    const resetButton =
        document.getElementById(
            "forgot-password-btn"
        );


    const emailInput =
        document.getElementById(
            "auth-email"
        );


    const passwordInput =
        document.getElementById(
            "auth-password"
        );


    const confirmInput =
        document.getElementById(
            "auth-confirm"
        );


    // ============================================================
    // GOOGLE
    // ============================================================

    if (googleButton) {

        googleButton.addEventListener(
            "click",
            async function () {

                googleButton.disabled =
                    true;


                setStatus(
                    "Opening Google sign-in…",
                    "info"
                );


                try {

                    await googleLogin();

                } catch (error) {

                    console.error(
                        "Google login error:",
                        error
                    );


                    setStatus(
                        authErrorMessage(
                            error
                        )
                    );


                    googleButton.disabled =
                        false;
                }
            }
        );
    }


    // ============================================================
    // PASSWORD RESET
    // ============================================================

    if (resetButton) {

        resetButton.addEventListener(
            "click",
            async function () {

                const email =
                    emailInput?.value.trim();


                if (!email) {

                    setStatus(
                        "Enter your email first, then choose Forgot password."
                    );


                    emailInput?.focus();

                    return;
                }


                resetButton.disabled =
                    true;


                try {

                    await sendPasswordResetEmail(
                        auth,
                        email
                    );


                    setStatus(
                        "Password reset link sent. Check your email.",
                        "success"
                    );

                } catch (error) {

                    console.error(
                        "Password reset error:",
                        error
                    );


                    setStatus(
                        authErrorMessage(
                            error
                        )
                    );

                } finally {

                    resetButton.disabled =
                        false;
                }
            }
        );
    }


    // ============================================================
    // EMAIL LOGIN / SIGNUP
    // ============================================================

    if (form) {

        form.addEventListener(
            "submit",
            async function (event) {

                event.preventDefault();


                const email =
                    emailInput?.value.trim() ||
                    "";


                const password =
                    passwordInput?.value ||
                    "";


                const isSignup =
                    form.dataset.mode ===
                    "signup";


                if (
                    !email ||
                    !password
                ) {

                    setStatus(
                        "Enter your email and password."
                    );

                    return;
                }


                if (
                    isSignup &&
                    password !==
                    (confirmInput?.value || "")
                ) {

                    setStatus(
                        "Passwords do not match."
                    );

                    return;
                }


                const submitButton =
                    form.querySelector(
                        "button[type=submit]"
                    );


                if (submitButton) {
                    submitButton.disabled =
                        true;
                }


                setStatus(
                    isSignup
                        ? "Creating your account…"
                        : "Signing in…",
                    "info"
                );


                try {

                    const result =
                        isSignup
                            ? await createUserWithEmailAndPassword(
                                auth,
                                email,
                                password
                            )
                            : await signInWithEmailAndPassword(
                                auth,
                                email,
                                password
                            );


                    await completeLogin(
                        result.user
                    );

                } catch (error) {

                    console.error(
                        "Authentication error:",
                        error
                    );


                    setStatus(
                        authErrorMessage(
                            error
                        )
                    );


                    if (submitButton) {
                        submitButton.disabled =
                            false;
                    }
                }
            }
        );
    }
}


// ============================================================
// LOGOUT
// ============================================================

async function wireLogout() {

    const button =
        document.getElementById(
            "logout-btn"
        );


    if (!button) {
        return;
    }


    button.addEventListener(
        "click",
        async function () {

            button.disabled =
                true;


            try {

                if (auth) {
                    await signOut(auth);
                }

            } catch (error) {

                console.warn(
                    "Firebase sign-out failed:",
                    error
                );
            }


            try {

                await fetch(
                    "/logout",
                    {
                        method: "POST",
                        credentials:
                            "same-origin"
                    }
                );

            } catch (error) {

                console.warn(
                    "Server logout failed:",
                    error
                );
            }


            window.location.href =
                "/";
        }
    );
}


// ============================================================
// INITIALIZE
// ============================================================

(async function () {

    // Wire logout first: it must still clear the server session even
    // if Firebase fails to load (wireLogout checks `auth` at click time).
    await wireLogout();

    try {

        await loadFirebase();

        await wireAuthPage();

    } catch (error) {

        console.error(
            "Firebase initialization error:",
            error
        );


        setStatus(
            "Firebase authentication is not configured yet. Add the Firebase web configuration to the server environment."
        );
    }

})();