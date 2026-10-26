from pathlib import Path
import cv2
import matplotlib.pyplot as plt

# Charger la photo située à côté de ce fichier
chemin = Path(__file__).with_name("pierre.jpg")
image = cv2.imread(str(chemin))

if image is None:
    raise SystemExit(
        "Photo introuvable : vérifie que pierre.jpg est à côté de test_canny.py."
    )

# Préparer l'image et détecter les contours
# Réduire la photo à 1600 pixels maximum
hauteur, largeur = image.shape[:2]
facteur = min(1, 1600 / max(hauteur, largeur))

image = cv2.resize(
    image,
    (round(largeur * facteur), round(hauteur * facteur)),
    interpolation=cv2.INTER_AREA
)

gris = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

# Lisser les textures en préservant les bords
flou = cv2.bilateralFilter(gris, 9, 100, 75)

# Détecter les contours
contours = cv2.Canny(flou, 70, 80)

# Afficher la photo et le résultat
fig, axes = plt.subplots(1, 2, figsize=(12, 6))

axes[0].imshow(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
axes[0].set_title("Photo originale")

axes[1].imshow(contours, cmap="gray")
axes[1].set_title("Contours détectés")

for axe in axes:
    axe.axis("off")

plt.tight_layout()
plt.show()

