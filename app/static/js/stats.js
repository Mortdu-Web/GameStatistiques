/**
 * stats.js — page Statistiques
 *
 * Charge et affiche : vue d'ensemble, classement général, détail par jeu (avec historique des parties)
 * et détail par joueur (avec historique dépliable par jeu), via l'API JSON du blueprint « statistiques ».
 * La racine de l'API (préfixe d'URL inclus) est lue dans l'attribut data-api de .stats.
 */
(() => {
  "use strict";

  const root = document.querySelector(".stats");
  const API = root.dataset.api;
  const $ = (id) => document.getElementById(id);

  // Historiques « joueur × jeu » déjà chargés : "joueurId-jeuId" -> parties
  const cacheJoueurJeu = new Map();

  // Numéros de requête : ignore la réponse d'une requête périmée si l'utilisateur a changé de sélection.
  let reqJeu = 0;
  let reqJoueur = 0;

  // ─── Utilitaires ────────────────────────────────────────────────────────────

  const ESC = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
  // Les noms de joueurs sont saisis par les utilisateurs : toujours échapper avant d'injecter dans le HTML.
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ESC[c]);
  const fullName = (p) => esc(`${p.prenom ?? ""} ${p.nom ?? ""}`.trim());
  const fmt = (v) =>
    v == null
      ? "—"
      : Number.isInteger(v)
        ? String(v)
        : v.toLocaleString("fr-FR", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  const pct = (v) => `${v ?? 0} %`;

  function fmtDate(iso) {
    if (!iso) return "";
    const [y, m, d] = iso.split("-").map(Number);
    return new Date(y, m - 1, d).toLocaleDateString("fr-FR", { day: "numeric", month: "short", year: "numeric" });
  }

  async function getJSON(path) {
    const res = await fetch(`${API}${path}`, {
      headers: { Accept: "application/json" }, // auth_client répond alors 401 en JSON au lieu d'une redirection
      credentials: "same-origin",
    });
    if (res.status === 401) {
      location.reload(); // session expirée : la page elle-même redirige vers la connexion
      throw new Error("Session expirée");
    }
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
  }

  const kpi = (valeur, libelle, { gold = false } = {}) =>
    `<div class="kpi${gold ? " is-gold" : ""}">
       <span class="kpi-value">${valeur}</span>
       <span class="kpi-label">${libelle}</span>
     </div>`;

  // Rang « à la compétition » : les ex æquo (mêmes victoires, % et parties) partagent le même rang.
  function avecRangs(liste) {
    let precedent = null;
    let rang = 0;
    return liste.map((j, i) => {
      const cle = `${j.nb_premiere}|${j.taux_victoire}|${j.nb_parties}`;
      if (cle !== precedent) rang = i + 1;
      precedent = cle;
      return { ...j, rang };
    });
  }

  function choisir(selectId, valeur) {
    const select = $(selectId);
    select.value = String(valeur);
    select.dispatchEvent(new Event("change"));
    const reduit = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    select.closest("section").scrollIntoView({ behavior: reduit ? "auto" : "smooth", block: "start" });
  }

  // ─── Vue d'ensemble + classement général ────────────────────────────────────

  async function chargerVueEnsemble() {
    try {
      const data = await getJSON("/global");
      afficherKpis(data);
      afficherTuiles(data.parties_par_jeu);
      afficherClassementGlobal(data.classement);
    } catch (err) {
      console.error("Erreur lors du chargement des statistiques globales :", err);
      $("parties-par-jeu").innerHTML = '<p class="stats-empty">Impossible de charger les statistiques.</p>';
      $("classement-global-body").innerHTML =
        '<tr><td colspan="6" class="stats-empty">Impossible de charger les statistiques.</td></tr>';
    }
  }

  function afficherKpis({ parties_par_jeu: jeux, classement }) {
    const total = (jeux || []).reduce((somme, j) => somme + j.nb_parties, 0);
    const jeuxJoues = (jeux || []).filter((j) => j.nb_parties > 0).length;
    const container = $("kpis");
    container.innerHTML =
      kpi(total, "Parties jouées", { gold: true }) +
      kpi(jeuxJoues, jeuxJoues > 1 ? "Jeux joués" : "Jeu joué") +
      kpi((classement || []).length, (classement || []).length > 1 ? "Joueurs actifs" : "Joueur actif");
    container.hidden = false;
  }

  function afficherTuiles(liste) {
    const container = $("parties-par-jeu");
    if (!liste || liste.length === 0) {
      container.innerHTML = '<p class="stats-empty">Aucun jeu enregistré.</p>';
      return;
    }
    container.innerHTML = liste
      .map(
        (jeu) => `
        <button type="button" class="game-tile${jeu.nb_parties === 0 ? " is-empty" : ""}" data-jeu-id="${esc(jeu.jeu_id)}">
          <span class="game-tile-name">${esc(jeu.label)}</span>
          <span class="game-tile-count"><strong>${jeu.nb_parties}</strong> ${jeu.nb_parties > 1 ? "parties" : "partie"}</span>
        </button>`
      )
      .join("");
  }

  function afficherClassementGlobal(liste) {
    const tbody = $("classement-global-body");
    if (!liste || liste.length === 0) {
      tbody.innerHTML =
        '<tr><td colspan="6" class="stats-empty">Aucune partie complète enregistrée pour le moment.</td></tr>';
      return;
    }
    tbody.innerHTML = avecRangs(liste)
      .map(
        (j) => `
        <tr class="${j.rang === 1 ? "is-first" : ""}">
          <td class="col-rank">${j.rang}</td>
          <td class="td-left"><button type="button" class="link-btn" data-joueur-id="${esc(j.id)}">${fullName(j)}</button></td>
          <td>${j.nb_parties}</td>
          <td><span class="stats-badge gold">${j.nb_premiere}</span></td>
          <td>${pct(j.taux_victoire)}</td>
          <td>${j.nb_derniere}</td>
        </tr>`
      )
      .join("");
  }

  // ─── Statistiques par jeu ───────────────────────────────────────────────────

  function replierHistoriqueJeu() {
    const liste = $("jeu-parties-list");
    const bouton = $("toggle-jeu-parties");
    liste.hidden = true;
    liste.innerHTML = "";
    bouton.textContent = "Afficher l’historique des parties";
    bouton.setAttribute("aria-expanded", "false");
  }

  function resetSectionJeu() {
    reqJeu++;
    $("jeu-extremes").hidden = true;
    $("table-jeu-wrap").hidden = true;
    $("jeu-empty").hidden = true;
    $("jeu-parties-wrap").hidden = true;
    replierHistoriqueJeu();
  }

  async function chargerStatsJeu(jeuId) {
    const moi = ++reqJeu;
    replierHistoriqueJeu(); // on replie l'historique à chaque changement de jeu

    try {
      const data = await getJSON(`/jeu/${encodeURIComponent(jeuId)}`);
      if (moi !== reqJeu) return;

      if (!data.classement || data.classement.length === 0) {
        $("jeu-extremes").hidden = true;
        $("table-jeu-wrap").hidden = true;
        $("jeu-parties-wrap").hidden = true;
        $("jeu-empty").textContent = "Aucune partie complète enregistrée pour ce jeu.";
        $("jeu-empty").hidden = false;
        return;
      }

      afficherExtremesJeu(data.extremes);

      $("classement-jeu-body").innerHTML = avecRangs(data.classement)
        .map(
          (j) => `
          <tr class="${j.rang === 1 ? "is-first" : ""}">
            <td class="col-rank">${j.rang}</td>
            <td class="td-left">${fullName(j)}</td>
            <td>${j.nb_parties}</td>
            <td><span class="stats-badge gold">${j.nb_premiere}</span></td>
            <td>${pct(j.taux_victoire)}</td>
            <td>${j.nb_derniere}</td>
            <td>${fmt(j.score_moyen)}</td>
            <td>${fmt(j.score_min)}</td>
            <td>${fmt(j.score_max)}</td>
          </tr>`
        )
        .join("");

      $("jeu-empty").hidden = true;
      $("table-jeu-wrap").hidden = false;

      $("jeu-parties-list").innerHTML = renderParties(data.parties);
      $("jeu-parties-wrap").hidden = false;
    } catch (err) {
      if (moi !== reqJeu) return;
      console.error("Erreur lors du chargement des statistiques du jeu :", err);
      $("jeu-extremes").hidden = true;
      $("table-jeu-wrap").hidden = true;
      $("jeu-parties-wrap").hidden = true;
      $("jeu-empty").textContent = "Impossible de charger les statistiques pour ce jeu.";
      $("jeu-empty").hidden = false;
    }
  }

  function afficherExtremesJeu(extremes) {
    const container = $("jeu-extremes");
    const bas = extremes?.score_plus_bas;
    const haut = extremes?.score_plus_haut;
    if (!bas && !haut) {
      container.hidden = true;
      container.innerHTML = "";
      return;
    }
    const carte = (e, titre) =>
      e ? kpi(esc(e.score), `${titre} — ${fullName(e)}<br>${esc(fmtDate(e.date))}`) : "";
    container.innerHTML = carte(bas, "Score le plus bas") + carte(haut, "Score le plus haut");
    container.hidden = false;
  }

  // ─── Statistiques par joueur ────────────────────────────────────────────────

  function resetSectionJoueur() {
    reqJoueur++;
    $("joueur-totaux").hidden = true;
    $("table-joueur-wrap").hidden = true;
    $("joueur-empty").hidden = true;
    $("joueur-hint").hidden = true;
  }

  async function chargerStatsJoueur(joueurId) {
    const moi = ++reqJoueur;

    try {
      const data = await getJSON(`/joueur/${encodeURIComponent(joueurId)}`);
      if (moi !== reqJoueur) return;

      $("joueur-totaux").innerHTML =
        kpi(data.nb_parties_total, "Parties jouées") +
        kpi(data.nb_premiere_total, "1<sup>ère</sup> place", { gold: true }) +
        kpi(pct(data.taux_victoire_total), "Victoires") +
        kpi(data.nb_derniere_total, "Dernière place");
      $("joueur-totaux").hidden = false;

      if (!data.par_jeu || data.par_jeu.length === 0) {
        $("table-joueur-wrap").hidden = true;
        $("joueur-hint").hidden = true;
        $("joueur-empty").textContent = "Ce joueur n’a encore aucune partie complète enregistrée.";
        $("joueur-empty").hidden = false;
        return;
      }

      $("stats-joueur-body").innerHTML = data.par_jeu
        .map(
          (j) => `
          <tr class="joueur-jeu-row" data-joueur-id="${esc(data.id)}" data-jeu-id="${esc(j.jeu_id)}"
              tabindex="0" role="button" aria-expanded="false">
            <td class="td-left">${esc(j.jeu)}</td>
            <td>${j.nb_parties}</td>
            <td><span class="stats-badge gold">${j.nb_premiere}</span></td>
            <td>${pct(j.taux_victoire)}</td>
            <td>${j.nb_derniere}</td>
            <td>${fmt(j.score_moyen)}</td>
            <td>${fmt(j.score_min)}</td>
            <td>${fmt(j.score_max)}</td>
          </tr>`
        )
        .join("");

      $("joueur-empty").hidden = true;
      $("table-joueur-wrap").hidden = false;
      $("joueur-hint").hidden = false;
    } catch (err) {
      if (moi !== reqJoueur) return;
      console.error("Erreur lors du chargement des statistiques du joueur :", err);
      $("joueur-totaux").hidden = true;
      $("table-joueur-wrap").hidden = true;
      $("joueur-hint").hidden = true;
      $("joueur-empty").textContent = "Impossible de charger les statistiques pour ce joueur.";
      $("joueur-empty").hidden = false;
    }
  }

  async function basculerDetailJoueurJeu(row) {
    const { joueurId, jeuId } = row.dataset;
    const suivante = row.nextElementSibling;

    // Détail déjà créé juste en dessous : on replie / déplie simplement.
    if (suivante && suivante.classList.contains("joueur-jeu-detail-row")) {
      const ouvrir = suivante.hidden;
      suivante.hidden = !ouvrir;
      row.setAttribute("aria-expanded", String(ouvrir));
      return;
    }

    // Sinon : création de la ligne de détail, puis chargement (avec cache).
    const detail = document.createElement("tr");
    detail.className = "joueur-jeu-detail-row";
    detail.innerHTML = `<td colspan="${row.children.length}"><p class="stats-loading">Chargement…</p></td>`;
    row.insertAdjacentElement("afterend", detail);
    row.setAttribute("aria-expanded", "true");

    const cle = `${joueurId}-${jeuId}`;
    try {
      let parties = cacheJoueurJeu.get(cle);
      if (!parties) {
        parties = await getJSON(`/joueur/${encodeURIComponent(joueurId)}/jeu/${encodeURIComponent(jeuId)}`);
        cacheJoueurJeu.set(cle, parties);
      }
      detail.firstElementChild.innerHTML = `<div class="parties-list">${renderParties(parties)}</div>`;
    } catch (err) {
      console.error("Erreur lors du chargement du détail des parties :", err);
      detail.firstElementChild.innerHTML = '<p class="stats-empty">Impossible de charger le détail des parties.</p>';
    }
  }

  // ─── Rendu commun : parties avec le score de chaque joueur ──────────────────

  function renderParties(parties) {
    if (!parties || parties.length === 0) {
      return '<p class="stats-empty">Aucune partie enregistrée.</p>';
    }
    return parties
      .map(
        (p) => `
        <div class="partie-card">
          <div class="partie-card-header">
            <span>Partie n°${esc(p.partie_id)}</span>
            <span>${esc(fmtDate(p.date))}</span>
          </div>
          <ul class="partie-scores">
            ${p.scores
              .map(
                (s) => `
              <li class="${s.gagnant ? "is-winner" : ""}">
                <span>${fullName(s)}${s.gagnant ? " ★" : ""}</span>
                <strong>${esc(s.score)}</strong>
              </li>`
              )
              .join("")}
          </ul>
        </div>`
      )
      .join("");
  }

  // ─── Initialisation ─────────────────────────────────────────────────────────

  document.addEventListener("DOMContentLoaded", () => {
    chargerVueEnsemble();

    $("select-jeu").addEventListener("change", (e) => {
      e.target.value ? chargerStatsJeu(e.target.value) : resetSectionJeu();
    });

    $("select-joueur").addEventListener("change", (e) => {
      e.target.value ? chargerStatsJoueur(e.target.value) : resetSectionJoueur();
    });

    $("toggle-jeu-parties").addEventListener("click", (e) => {
      const liste = $("jeu-parties-list");
      const ouvert = !liste.hidden;
      liste.hidden = ouvert;
      e.currentTarget.setAttribute("aria-expanded", String(!ouvert));
      e.currentTarget.textContent = ouvert
        ? "Afficher l’historique des parties"
        : "Masquer l’historique des parties";
    });

    // Un clic sur une tuile de jeu ou sur un nom du classement ouvre la section correspondante.
    $("parties-par-jeu").addEventListener("click", (e) => {
      const tuile = e.target.closest("[data-jeu-id]");
      if (tuile) choisir("select-jeu", tuile.dataset.jeuId);
    });
    $("classement-global-body").addEventListener("click", (e) => {
      const lien = e.target.closest("[data-joueur-id]");
      if (lien) choisir("select-joueur", lien.dataset.joueurId);
    });

    // Délégation : un clic (ou Entrée / Espace) sur une ligne « jeu » déplie l'historique du joueur pour ce jeu.
    const corpsJoueur = $("stats-joueur-body");
    corpsJoueur.addEventListener("click", (e) => {
      const row = e.target.closest("tr.joueur-jeu-row");
      if (row) basculerDetailJoueurJeu(row);
    });
    corpsJoueur.addEventListener("keydown", (e) => {
      if (e.key !== "Enter" && e.key !== " ") return;
      const row = e.target.closest("tr.joueur-jeu-row");
      if (!row || e.target !== row) return;
      e.preventDefault();
      basculerDetailJoueurJeu(row);
    });
  });
})();
