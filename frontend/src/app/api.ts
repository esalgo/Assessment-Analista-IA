import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable, tap } from 'rxjs';

// Caddy publica la API bajo /api en el mismo dominio: no hay CORS ni URL por entorno.
const API = '/api';
const CLAVE_TOKEN = 'token';

export interface Sesion {
  empresa_id: string;
  asesor_id: string | null;
  rol: 'asesor' | 'gerente';
}

export interface LeadCola {
  cola: 'primer_contacto' | 'seguimiento';
  orden: number;
  lead_id: string;
  nombre_cliente: string;
  telefono: string;
  canal: string;
  score: number;
  temperatura: 'alta' | 'media' | 'baja';
  estado: string;
  horas_transcurridas: string;
  sin_senal_conversacional: boolean;
}

export interface ColaDelDia {
  fecha: string;
  asesor: { asesor_id: string; nombre: string; punto_venta_id: string };
  leads: LeadCola[];
}

export interface Factor {
  variable: string;
  valor: string;
  puntos?: number;
  multiplicador?: number;
  regla?: string;
}

export interface SkuFuente {
  texto: string | null;
  sku: string | null;
  modelo: string | null;
}

export interface LeadDelCliente {
  lead_id: string;
  canal: string;
  punto_venta_id: string;
  fecha_registro: string;
  estado_gestion: string;
  sku: { formulario: SkuFuente; conversacion: SkuFuente; difieren: boolean };
  extraccion: {
    justificacion: string;
    pidio_cita: string;
    manifesto_cuota_inicial: string;
    cuota_inicial_cop: number | null;
    forma_pago: string;
    pidio_cotizacion: string;
    intencion_declarada: string;
    objecion_principal: string;
    violaciones: string[];
  } | null;
}

export interface DetalleCliente {
  cliente_id: string;
  nombre_cliente: string;
  telefono: string;
  email: string | null;
  score: {
    score: number;
    temperatura: string;
    cola: string;
    estado: string;
    horas_transcurridas: string;
    sin_senal_conversacional: boolean;
    factores: Factor[];
    score_version: string;
  } | null;
  leads: LeadDelCliente[];
}

export interface Asesor {
  asesor_id: string;
  nombre: string;
  punto_venta_id: string;
}

export interface ResumenPuntoVenta {
  punto_venta_id: string;
  asesores_activos: number;
  asesores_inactivos: number;
  capacidad_diaria: number;
  pendientes: number;
  seguimiento: number;
  clientes_activos: number;
  dias_de_cartera: number | null;
}

@Injectable({ providedIn: 'root' })
export class Api {
  private http = inject(HttpClient);

  token(): string | null {
    try {
      return sessionStorage.getItem(CLAVE_TOKEN);
    } catch {
      return null;
    }
  }

  /** Lee los claims del token solo para decidir qué mostrar. No es control de
   *  acceso: la API verifica la firma y aplica el rol y la empresa en cada request. */
  sesion(): Sesion | null {
    const token = this.token();
    if (!token) return null;
    try {
      const base64 = token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/');
      const claims = JSON.parse(atob(base64));
      if (claims.exp * 1000 < Date.now()) return null;
      return { empresa_id: claims.empresa_id, asesor_id: claims.asesor_id, rol: claims.rol };
    } catch {
      return null;
    }
  }

  login(email: string, password: string): Observable<{ access_token: string }> {
    return this.http
      .post<{ access_token: string }>(`${API}/auth/login`, { email, password })
      .pipe(tap((r) => sessionStorage.setItem(CLAVE_TOKEN, r.access_token)));
  }

  salir(): void {
    sessionStorage.removeItem(CLAVE_TOKEN);
  }

  colaDelDia(asesorId: string | null): Observable<ColaDelDia> {
    const params: Record<string, string> = asesorId ? { asesor_id: asesorId } : {};
    return this.http.get<ColaDelDia>(`${API}/leads/hoy`, { params });
  }

  detalle(leadId: string): Observable<DetalleCliente> {
    return this.http.get<DetalleCliente>(`${API}/leads/${encodeURIComponent(leadId)}`);
  }

  asesores(): Observable<Asesor[]> {
    return this.http.get<Asesor[]>(`${API}/asesores`);
  }

  resumen(): Observable<ResumenPuntoVenta[]> {
    return this.http.get<ResumenPuntoVenta[]>(`${API}/resumen`);
  }
}
