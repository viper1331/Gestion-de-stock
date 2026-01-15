# Sécurité 2FA (TOTP obligatoire)

## Vue d'ensemble

Le système 2FA TOTP fonctionne en deux étapes : authentification des identifiants, puis validation
du code TOTP avant l'émission d'un token/session. Quand le mode « 2FA obligatoire » est activé,
les utilisateurs doivent activer TOTP pour pouvoir se connecter.

## Flow d'authentification

### 1) Login sans 2FA activée

* **Mode obligatoire désactivé** → login classique, retour des tokens.
* **Mode obligatoire activé** → refus avec `detail=2FA_REQUIRED_SETUP`.

### 2) Login avec 2FA activée

1. `POST /auth/login` (username/password, sans code TOTP)  
   → retourne un challenge :

```json
{
  "status": "totp_required",
  "challenge_id": "...",
  "username": "...",
  "available_methods": ["totp"]
}
```

2. Validation du challenge (au choix) :

* `POST /auth/login` avec `totp_code` + `challenge_id`
* `POST /auth/2fa/verify` avec `challenge_id` + `code`
* `POST /auth/2fa/recovery` avec `challenge_id` + `recovery_code`

Le token/session n'est émis qu'après validation du TOTP/recovery.

## Détails de sécurité

* **Challenge unique** : usage unique, expiration rapide (TTL par défaut 120s).
* **Limite d'essais** : max 5 tentatives par challenge, puis cooldown (par défaut 300s).
* **Journaux** : seuls les succès/échecs sont loggés, jamais le code TOTP.

## Configuration admin

Le paramètre global est stocké dans `system_config.json` sous la clé :

```json
{
  "security": {
    "require_totp_for_login": true
  }
}
```

API admin :

* `GET /admin/security/settings`
* `PUT /admin/security/settings`  
  payload :

```json
{
  "require_totp_for_login": true
}
```
