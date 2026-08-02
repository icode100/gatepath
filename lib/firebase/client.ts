import {
  getApp,
  getApps,
  initializeApp,
  type FirebaseApp,
} from "firebase/app";
import {
  getAuth,
  inMemoryPersistence,
  setPersistence,
  type Auth,
} from "firebase/auth";

const firebaseConfig = {
  apiKey: process.env.NEXT_PUBLIC_FIREBASE_API_KEY,
  authDomain: process.env.NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN,
  projectId: process.env.NEXT_PUBLIC_FIREBASE_PROJECT_ID,
  appId: process.env.NEXT_PUBLIC_FIREBASE_APP_ID,
  measurementId: process.env.NEXT_PUBLIC_FIREBASE_MEASUREMENT_ID,
  messagingSenderId: process.env.NEXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID,
};

export const firebaseAuthConfigured = Boolean(
  firebaseConfig.apiKey &&
    firebaseConfig.authDomain &&
    firebaseConfig.projectId &&
    firebaseConfig.appId,
);

export const firebaseAnalyticsConfigured = Boolean(
  firebaseAuthConfigured && firebaseConfig.measurementId,
);

export function getFirebaseApp(): FirebaseApp | null {
  if (!firebaseAuthConfigured || typeof window === "undefined") return null;
  return getApps().length ? getApp() : initializeApp(firebaseConfig);
}

export function getFirebaseAuth(): Auth | null {
  const app = getFirebaseApp();
  return app ? getAuth(app) : null;
}

let preparedAuthPromise: Promise<Auth | null> | null = null;

export function getPreparedFirebaseAuth(): Promise<Auth | null> {
  if (preparedAuthPromise) return preparedAuthPromise;
  const auth = getFirebaseAuth();
  if (!auth) return Promise.resolve(null);
  preparedAuthPromise = setPersistence(auth, inMemoryPersistence).then(
    () => auth,
  );
  return preparedAuthPromise;
}
