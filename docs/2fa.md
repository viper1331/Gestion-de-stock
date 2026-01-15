# Authentification 2FA (TOTP)

Cette fonctionnalité ajoute une authentification en deux étapes basée sur TOTP, avec codes de récupération et appareils de confiance.

## Enrôlement

1. Dans **Paramètres > Sécurité**, cliquez sur **Activer 2FA**.
2. Scannez le QR code avec une application Authenticator.
3. Entrez le code TOTP pour confirmer.
4. Les **10 codes de récupération** s’affichent une seule fois : sauvegardez-les.

## Connexion 2 étapes

1. Identifiant + mot de passe.
2. Code TOTP ou code de récupération.
3. Optionnel : **Se souvenir de cet appareil pendant 30 jours** (cookie httpOnly signé).

## Désactivation

Dans **Paramètres > Sécurité**, fournissez votre mot de passe et un code TOTP (ou un code de récupération) pour désactiver la 2FA.

## Appareils de confiance

Lorsque l’option « Se souvenir de cet appareil » est activée pendant la vérification 2FA, un cookie sécurisé est posé pour 30 jours. Tant qu’il est valide, l’étape 2FA est contournée pour cet appareil.

## Variables d’environnement

Obligatoire en production :

- `TWO_FACTOR_ENCRYPTION_KEY` : clé Fernet base64 (32 octets). Exemple :
  ```bash
  python - <<'PY'
  from cryptography.fernet import Fernet
  print(Fernet.generate_key().decode())
  PY
  ```

Optionnel :

- `ALLOW_INSECURE_2FA_DEV=1` : autorise un chiffrement éphémère en développement si la clé est absente.
- `TWO_FACTOR_CHALLENGE_TTL_SECONDS=300`
- `TWO_FACTOR_TRUSTED_DEVICE_DAYS=30`
- `TWO_FACTOR_RATE_LIMIT_ATTEMPTS=5`
- `TWO_FACTOR_RATE_LIMIT_WINDOW_SECONDS=300`
