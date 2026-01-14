# Règles de layout responsive

## Principes généraux
- Toutes les pages métiers doivent rester fluides du mobile au desktop.
- Pas de scroll horizontal sur des écrans standards.
- Le scroll principal est géré par `AppLayout` (pas de pièges de scroll imbriqués).
- Les tables défilent dans leur carte (`overflow-auto`), pas sur la page entière.
- Les panels latéraux se replient sous le contenu en viewport réduit.

## Interdictions (anti-regression)
Dans `frontend/src/features/**` et `frontend/src/components/**` :
- classes Tailwind `w-[Npx]`, `min-w-[Npx]`, `max-w-[Npx]`
- styles inline `width/minWidth/maxWidth` en pixels
- `h-[Npx]` sur les conteneurs dynamiques (sauf exceptions média)

## Vérification automatisée
Un guard dédié est disponible :

```
npm -C frontend run lint:layout
```

Le script analyse les composants et échoue si un pattern interdit est détecté.

## Recommandations
- Utiliser `min-w-0` sur les conteneurs flex et grids.
- Préférer `w-full`, `flex`, `grid` et `overflow-auto` pour les tables.
- Vérifier le rendu avec des breakpoints `xs/sm/md/lg`.
