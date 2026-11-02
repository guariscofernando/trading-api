// Mesa de práctica: cliente de la API de paper trading. Sin dependencias ni HTML construido con datos:
// todo lo que viene del servidor entra con textContent (nunca como HTML), y la CSP de /app bloquea scripts en línea.
(() => {
  "use strict";

  const MONEDAS = ["bitcoin", "ethereum", "solana", "ripple", "cardano", "dogecoin", "binancecoin", "litecoin"];
  const REFRESCO_MS = 20000;
  const CLAVE_TOKEN = "mesa.token";

  const $ = (id) => document.getElementById(id);
  const estado = { token: null, usuario: null, precios: {}, idOrden: null, temporizador: null, cargando: false };

  // ------------------------------------------------------------------ utilidades
  function el(etiqueta, props = {}, ...hijos) {
    const nodo = document.createElement(etiqueta);
    for (const [k, v] of Object.entries(props)) {
      if (k === "class") nodo.className = v;
      else if (k === "text") nodo.textContent = v;
      else if (k.startsWith("on")) nodo.addEventListener(k.slice(2), v);
      else nodo.setAttribute(k, v);
    }
    for (const h of hijos) if (h != null) nodo.append(h);
    return nodo;
  }
  const guardar = (k, v) => { try { v == null ? sessionStorage.removeItem(k) : sessionStorage.setItem(k, v); } catch (e) { /* sin almacenamiento: la sesión vive en memoria */ } };
  const leer = (k) => { try { return sessionStorage.getItem(k); } catch (e) { return null; } };

  // useGrouping "always": en español 4 cifras no llevan separador por defecto (2450,50), pero en una mesa de precios sí (2.450,50).
  const fNum = new Intl.NumberFormat("es", { maximumFractionDigits: 8, useGrouping: "always" });
  const fUsd = new Intl.NumberFormat("es", { minimumFractionDigits: 2, maximumFractionDigits: 2, useGrouping: "always" });
  const fPrecio = (n) => (n == null ? "—" : new Intl.NumberFormat("es", { minimumFractionDigits: 2, maximumFractionDigits: Math.abs(n) < 1 ? 6 : 2, useGrouping: "always" }).format(n));
  const usd = (n) => (n == null ? "—" : fUsd.format(n));
  const conSigno = (n) => (n == null ? "—" : (n > 0 ? "+" : n < 0 ? "−" : "") + fUsd.format(Math.abs(n)));
  const clase = (n) => (n > 0 ? "gana" : n < 0 ? "pierde" : "");

  function decimal(texto) {
    // Acepta "0,001" o "0.001"; devuelve un número o null si no es un decimal positivo.
    const t = String(texto).trim().replace(",", ".");
    if (!/^\d+(\.\d+)?$/.test(t)) return null;
    const n = Number(t);
    return Number.isFinite(n) && n > 0 ? n : null;
  }

  function avisar(texto, tipo = "") {
    const a = $("aviso");
    if (!texto) { a.hidden = true; return; }
    a.textContent = texto;
    a.className = "aviso " + tipo;
    a.hidden = false;
  }

  function mensajeDeError(cuerpo, estadoHttp) {
    const d = cuerpo && cuerpo.detail;
    if (typeof d === "string") return d;
    if (Array.isArray(d) && d.length) return d.map((e) => (e.loc ? e.loc.filter((x) => x !== "body").join(".") + ": " : "") + (e.msg || "dato inválido")).join(". ");
    if (estadoHttp === 429) return "Demasiadas peticiones. Espera un momento e inténtalo de nuevo.";
    if (estadoHttp >= 500) return "El servidor no pudo completar la operación. Inténtalo de nuevo en unos segundos.";
    return "No se pudo completar la operación.";
  }

  async function api(ruta, { metodo = "GET", cuerpo, auth = true } = {}) {
    const cabeceras = {};
    if (cuerpo !== undefined) cabeceras["Content-Type"] = "application/json";
    if (auth && estado.token) cabeceras.Authorization = "Bearer " + estado.token;
    let r;
    try {
      r = await fetch(ruta, { method: metodo, headers: cabeceras, body: cuerpo !== undefined ? JSON.stringify(cuerpo) : undefined });
    } catch (e) {
      throw Object.assign(new Error("Sin conexión con el servidor. Revisa tu red e inténtalo de nuevo."), { red: true });
    }
    let datos = null;
    try { datos = await r.json(); } catch (e) { /* respuesta sin cuerpo */ }
    if (r.status === 401 && auth && estado.token) {
      cerrarLocal("Tu sesión terminó. Entra de nuevo para continuar.");
      throw Object.assign(new Error("sesión terminada"), { silencioso: true });
    }
    if (!r.ok) throw Object.assign(new Error(mensajeDeError(datos, r.status)), { estadoHttp: r.status });
    return datos;
  }

  // ------------------------------------------------------------------ sesión
  function mostrar(vista) {
    $("vista-acceso").hidden = vista !== "acceso";
    $("vista-mesa").hidden = vista !== "mesa";
    $("sesion").hidden = vista !== "mesa";
  }

  function cerrarLocal(mensaje) {
    clearInterval(estado.temporizador);
    estado.token = null; estado.usuario = null;
    guardar(CLAVE_TOKEN, null);
    mostrar("acceso");
    avisar(mensaje || "", mensaje ? "error" : "");
  }

  async function entrar(token) {
    estado.token = token;
    guardar(CLAVE_TOKEN, token);
    const yo = await api("/usuarios/me");
    estado.usuario = yo.username;
    $("usuario").textContent = yo.username;
    mostrar("mesa");
    avisar("");
    await refrescarTodo();
    clearInterval(estado.temporizador);
    estado.temporizador = setInterval(() => { if (document.visibilityState === "visible") refrescarTodo(); }, REFRESCO_MS);
  }

  async function enviarAcceso(ev, registro) {
    ev.preventDefault();
    const f = ev.target, boton = f.querySelector("button[type=submit]");
    const datos = Object.fromEntries(new FormData(f));
    boton.disabled = true;
    try {
      if (registro) {
        await api("/usuarios/registro", { metodo: "POST", auth: false, cuerpo: { username: datos.username, email: datos.email, password: datos.password } });
      }
      const sesion = await api("/usuarios/login", { metodo: "POST", auth: false, cuerpo: { username: datos.username, password: datos.password } });
      f.reset();
      await entrar(sesion.access_token);
    } catch (e) {
      if (!e.silencioso) avisar(e.message, "error");
    } finally {
      boton.disabled = false;
    }
  }

  async function salir() {
    try { await api("/usuarios/logout", { metodo: "POST" }); } catch (e) { /* si falla igual se cierra aquí */ }
    cerrarLocal("");
    avisar("Cerraste sesión en todos tus dispositivos.", "ok");
  }

  // ------------------------------------------------------------------ pestañas
  function pestanas(ids) {
    for (const [tab, panel] of ids) {
      $(tab).addEventListener("click", () => {
        for (const [t, p] of ids) {
          $(t).setAttribute("aria-selected", String(t === tab));
          if (p) $(p).hidden = t !== tab;
        }
      });
    }
  }

  // ------------------------------------------------------------------ datos
  async function refrescarTodo() {
    if (estado.cargando) return;
    estado.cargando = true;
    try {
      const [b, abiertas, hist] = await Promise.all([
        api("/paper/billetera"), api("/paper/ordenes?estado=ABIERTA"), api("/paper/historial?limit=50"),
      ]);
      pintarCartera(b); pintarPosiciones(b.posiciones); pintarAbiertas(abiertas); pintarHistorial(hist);
    } catch (e) {
      if (!e.silencioso) avisar(e.message, "error");
    } finally {
      estado.cargando = false;
    }
    cargarPrecios();
  }

  async function cargarPrecios() {
    try {
      const datos = await api("/precios/multiples?coins=" + MONEDAS.join(","), { auth: false });
      estado.precios = datos;
      pintarPrecios(datos); actualizarEstimado();
    } catch (e) { /* los precios son informativos: un fallo no interrumpe nada */ }
  }

  // ------------------------------------------------------------------ pintado
  function pintarCartera(b) {
    $("equity").textContent = usd(b.equity) + " USDT";
    const p = $("pnl");
    p.className = "variacion " + clase(b.pnl_total);
    const pct = b.saldo_inicial ? (b.pnl_total / b.saldo_inicial) * 100 : 0;
    p.textContent = conSigno(b.pnl_total) + " USDT (" + (pct > 0 ? "+" : pct < 0 ? "−" : "") + Math.abs(pct).toFixed(2).replace(".", ",") + " %) desde el inicio";
    $("saldo").textContent = usd(b.saldo_usdt);
    $("en-posiciones").textContent = usd(b.valor_posiciones);
    const r = $("realizado"); r.textContent = conSigno(b.pnl_realizado); r.className = clase(b.pnl_realizado);
    $("aviso-valoracion").hidden = b.valoracion_completa !== false;
  }

  function pintarPosiciones(lista) {
    const cuerpo = $("tabla-posiciones").tBodies[0];
    cuerpo.replaceChildren();
    $("vacio-posiciones").hidden = lista.length > 0;
    for (const f of lista) {
      const res = el("td", { class: "num " + clase(f.pnl_no_realizado) },
        f.pnl_no_realizado == null ? "—" : conSigno(f.pnl_no_realizado) + (f.pnl_pct == null ? "" : " (" + (f.pnl_pct > 0 ? "+" : f.pnl_pct < 0 ? "−" : "") + Math.abs(f.pnl_pct).toFixed(2).replace(".", ",") + " %)"));
      const fila = el("tr", { class: "clicable", tabindex: "0", title: "Vender esta moneda", "aria-label": "Preparar una venta de " + f.coin_id },
        el("th", { scope: "row", text: f.coin_id }), el("td", { class: "num", text: fNum.format(f.cantidad) }),
        el("td", { class: "num", text: fPrecio(f.precio_medio) }), el("td", { class: "num", text: fPrecio(f.precio_actual) }),
        el("td", { class: "num", text: usd(f.valor_actual) }), res);
      const preparar = () => prepararVenta(f.coin_id, f.cantidad);
      fila.addEventListener("click", preparar);
      fila.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); preparar(); } });
      cuerpo.append(fila);
    }
  }

  const ETIQUETA_TIPO = { LIMIT: "Límite", STOP: "Stop", MARKET: "Mercado" };
  const insignia = (side) => el("span", { class: "insignia " + (side === "BUY" ? "compra" : "venta"), text: side === "BUY" ? "Compra" : "Venta" });

  function pintarAbiertas(lista) {
    const cuerpo = $("tabla-abiertas").tBodies[0];
    cuerpo.replaceChildren();
    $("vacio-abiertas").hidden = lista.length > 0;
    for (const o of lista) {
      const cancelar = el("button", { type: "button", class: "accion", text: "Cancelar", "aria-label": "Cancelar la orden " + o.id + " de " + o.coin_id });
      cancelar.addEventListener("click", () => cancelarOrden(o.id));
      cuerpo.append(el("tr", {},
        el("th", { scope: "row", text: o.coin_id }),
        el("td", {}, insignia(o.side), " " + (ETIQUETA_TIPO[o.tipo] || o.tipo)),
        el("td", { class: "num", text: fNum.format(o.cantidad) }), el("td", { class: "num", text: fPrecio(o.precio) }),
        el("td", { text: o.creada_en || "" }), el("td", {}, cancelar)));
    }
  }

  function pintarHistorial(lista) {
    const cuerpo = $("tabla-historial").tBodies[0];
    cuerpo.replaceChildren();
    $("vacio-historial").hidden = lista.length > 0;
    for (const t of lista) {
      cuerpo.append(el("tr", {},
        el("th", { scope: "row", text: t.coin_id }), el("td", {}, insignia(t.side)),
        el("td", { class: "num", text: fNum.format(t.cantidad) }), el("td", { class: "num", text: fPrecio(t.precio) }),
        el("td", { class: "num", text: usd(t.comision) }),
        el("td", { class: "num " + clase(t.pnl_realizado), text: t.side === "SELL" ? conSigno(t.pnl_realizado) : "—" }),
        el("td", { text: t.ejecutado_en || "" })));
    }
  }

  function pintarPrecios(datos) {
    const lista = $("precios");
    lista.replaceChildren();
    for (const id of MONEDAS) {
      const d = datos[id];
      if (!d || d.usd == null) continue;
      const cambio = d.usd_24h_change;
      const boton = el("button", { type: "button", "aria-label": "Usar " + id + " en la orden" },
        el("span", {}, el("span", { class: "moneda", text: id }),
          cambio == null ? null : el("span", { class: "cambio " + clase(cambio), text: (cambio > 0 ? "+" : cambio < 0 ? "−" : "") + Math.abs(cambio).toFixed(1).replace(".", ",") + " %" })),
        el("span", { text: fPrecio(d.usd) }));
      boton.addEventListener("click", () => { $("coin").value = id; actualizarEstimado(); $("cantidad").focus(); });
      lista.append(el("li", {}, boton));
    }
    if (!lista.children.length) lista.append(el("li", { class: "nota", text: "No hay precios disponibles ahora mismo." }));
  }

  // ------------------------------------------------------------------ orden
  const AYUDA = {
    MARKET: "",
    LIMIT: "Compra a tu precio o más barato; vende a tu precio o más caro. Se ejecuta sola cuando el mercado llega.",
    STOP: "Compra si el precio sube hasta tu nivel; vende si baja hasta él (stop-loss). Se ejecuta a mercado al activarse.",
  };

  function ladoActual() { return document.querySelector("input[name=side]:checked").value; }

  function actualizarFormulario() {
    const tipo = $("tipo").value, venta = ladoActual() === "SELL";
    $("fila-precio").hidden = tipo === "MARKET";
    $("ayuda-tipo").textContent = AYUDA[tipo];
    const b = $("enviar");
    b.textContent = (venta ? "Vender" : "Comprar") + (tipo === "MARKET" ? "" : " con orden " + ETIQUETA_TIPO[tipo].toLowerCase());
    b.classList.toggle("venta", venta);
    actualizarEstimado();
  }

  function actualizarEstimado() {
    const cant = decimal($("cantidad").value);
    const ref = $("tipo").value === "MARKET" ? (estado.precios[$("coin").value.trim().toLowerCase()] || {}).usd : decimal($("precio").value);
    $("estimado").textContent = cant && ref ? usd(cant * ref) + " USDT" : "—";
  }

  function prepararVenta(coin, cantidad) {
    $("lado-venta").checked = true;
    $("coin").value = coin; $("tipo").value = "MARKET"; $("cantidad").value = String(cantidad).replace(".", ",");
    actualizarFormulario();
    $("ticket").scrollIntoView({ block: "nearest", behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
    $("enviar").focus();
  }

  async function enviarOrden(ev) {
    ev.preventDefault();
    const tipo = $("tipo").value, side = ladoActual();
    const coin = $("coin").value.trim().toLowerCase();
    const cantidad = decimal($("cantidad").value);
    if (!coin) return avisar("Escribe la moneda (por ejemplo, bitcoin).", "error");
    if (!cantidad) return avisar("La cantidad debe ser un número mayor que cero, por ejemplo 0,001.", "error");
    let precio = null;
    if (tipo !== "MARKET") {
      precio = decimal($("precio").value);
      if (!precio) return avisar("Escribe el precio en USDT de la orden " + ETIQUETA_TIPO[tipo].toLowerCase() + ".", "error");
    }
    // El mismo client_order_id se reutiliza si el envío falla: reintentar no puede duplicar la orden.
    estado.idOrden = estado.idOrden || ("ui-" + (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + Math.random().toString(16).slice(2)));
    const cuerpo = { coin_id: coin, side, cantidad, client_order_id: estado.idOrden };
    const boton = $("enviar");
    boton.disabled = true;
    try {
      if (tipo === "MARKET") {
        const t = await api("/paper/orden", { metodo: "POST", cuerpo });
        avisar((side === "BUY" ? "Compraste " : "Vendiste ") + fNum.format(t.cantidad) + " " + t.coin_id + " a " + fPrecio(t.precio) + " USDT.", "ok");
      } else {
        const o = await api("/paper/ordenes", { metodo: "POST", cuerpo: { ...cuerpo, tipo, precio } });
        avisar("Orden " + ETIQUETA_TIPO[tipo].toLowerCase() + " creada: se ejecutará cuando el precio llegue a " + fPrecio(o.precio) + " USDT.", "ok");
      }
      estado.idOrden = null;
      $("cantidad").value = ""; $("precio").value = "";
      actualizarEstimado();
      await refrescarTodo();
    } catch (e) {
      if (e.estadoHttp && e.estadoHttp < 500 && e.estadoHttp !== 429) estado.idOrden = null;   // rechazo definitivo: la próxima es otra orden
      if (!e.silencioso) avisar(e.message, "error");
    } finally {
      boton.disabled = false;
    }
  }

  async function cancelarOrden(id) {
    try {
      await api("/paper/ordenes/" + encodeURIComponent(id), { metodo: "DELETE" });
      avisar("Orden cancelada.", "ok");
      await refrescarTodo();
    } catch (e) { if (!e.silencioso) avisar(e.message, "error"); }
  }

  async function reiniciar() {
    if (!confirm("Se borrarán tus posiciones, órdenes e historial y volverás a 10.000 USDT. ¿Continuar?")) return;
    try {
      await api("/paper/reiniciar", { metodo: "POST" });
      avisar("Cuenta reiniciada.", "ok");
      await refrescarTodo();
    } catch (e) { if (!e.silencioso) avisar(e.message, "error"); }
  }

  // ------------------------------------------------------------------ arranque
  function iniciar() {
    $("monedas").append(...MONEDAS.map((m) => el("option", { value: m })));
    $("tab-entrar").addEventListener("click", () => cambiarAcceso(false));
    $("tab-crear").addEventListener("click", () => cambiarAcceso(true));
    $("form-entrar").addEventListener("submit", (e) => enviarAcceso(e, false));
    $("form-crear").addEventListener("submit", (e) => enviarAcceso(e, true));
    $("salir").addEventListener("click", salir);
    $("ticket").addEventListener("submit", enviarOrden);
    for (const id of ["tipo", "lado-compra", "lado-venta"]) $(id).addEventListener("change", actualizarFormulario);
    for (const id of ["coin", "cantidad", "precio"]) $(id).addEventListener("input", actualizarEstimado);
    $("reiniciar").addEventListener("click", reiniciar);
    pestanas([["tab-abiertas", "panel-abiertas"], ["tab-historial", "panel-historial"]]);
    actualizarFormulario();

    const guardado = leer(CLAVE_TOKEN);
    if (guardado) {
      entrar(guardado).catch(() => { if (!estado.token) mostrar("acceso"); });
    } else {
      mostrar("acceso");
    }
  }

  function cambiarAcceso(registro) {
    $("tab-entrar").setAttribute("aria-selected", String(!registro));
    $("tab-crear").setAttribute("aria-selected", String(registro));
    $("form-entrar").hidden = registro; $("form-crear").hidden = !registro;
    avisar("");
  }

  iniciar();
})();
