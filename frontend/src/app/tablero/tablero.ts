import { Component, computed, inject, signal } from '@angular/core';
import { HttpErrorResponse } from '@angular/common/http';
import { Router } from '@angular/router';
import { Api, Asesor, ColaDelDia, DetalleCliente, Factor, LeadCola, ResumenPuntoVenta } from '../api';

// La base guarda identificadores sin tildes (decisión del día 1); aquí se traducen para leer.
const ESTADOS: Record<string, string> = {
  sin_gestion: 'Sin gestión',
  no_contesta: 'No contesta',
  contactado: 'Contactado',
  en_proceso: 'En proceso',
  cotizacion_enviada: 'Cotización enviada',
  descartado: 'Descartado',
};

const VARIABLES: Record<string, string> = {
  pidio_cita: 'Pidió cita',
  manifesto_cuota_inicial: 'Manifestó cuota inicial',
  forma_pago: 'Forma de pago',
  urgencia: 'Urgencia (horas sin contacto)',
};

const VALORES: Record<string, string> = {
  SI: 'Sí',
  NO: 'No',
  NO_INFORMA: 'No informa',
  no_informa: 'No informa',
  contado: 'Contado',
  credito: 'Crédito',
  compra_inmediata: 'Compra inmediata',
  comparando: 'Comparando',
  explorando: 'Explorando',
  descartado: 'Descartado',
  ninguna: 'Ninguna',
  precio: 'Precio',
  tasa: 'Tasa',
  cuota: 'Cuota mensual',
  disponibilidad: 'Disponibilidad',
  tramites: 'Trámites',
  sin_inicial: 'Sin cuota inicial',
  historial_crediticio: 'Historial crediticio',
  otra: 'Otra',
};

@Component({
  selector: 'app-tablero',
  templateUrl: './tablero.html',
})
export class Tablero {
  private api = inject(Api);
  private router = inject(Router);

  protected sesion = this.api.sesion();
  protected esGerente = this.sesion?.rol === 'gerente';

  protected asesores = signal<Asesor[]>([]);
  protected asesorId = signal<string | null>(null);
  protected resumen = signal<ResumenPuntoVenta[]>([]);
  protected cola = signal<ColaDelDia | null>(null);
  protected seleccionado = signal<string | null>(null);
  protected detalle = signal<DetalleCliente | null>(null);
  protected error = signal<string | null>(null);

  protected primerContacto = computed(() => this.leadsDeCola('primer_contacto'));
  protected seguimiento = computed(() => this.leadsDeCola('seguimiento'));

  constructor() {
    if (this.esGerente) {
      this.api.resumen().subscribe({ next: (r) => this.resumen.set(r), error: (e) => this.mostrarError(e) });
      this.api.asesores().subscribe({
        next: (lista) => {
          this.asesores.set(lista);
          if (lista.length) this.elegirAsesor(lista[0].asesor_id);
        },
        error: (e) => this.mostrarError(e),
      });
    } else {
      this.cargarCola();
    }
  }

  elegirAsesor(asesorId: string): void {
    this.asesorId.set(asesorId);
    this.cargarCola();
  }

  abrir(lead: LeadCola): void {
    this.seleccionado.set(lead.lead_id);
    this.detalle.set(null);
    this.api.detalle(lead.lead_id).subscribe({
      // Si el usuario ya abrió otro lead, esta respuesta llegó tarde y se descarta.
      next: (d) => this.seleccionado() === lead.lead_id && this.detalle.set(d),
      error: (e) => this.mostrarError(e),
    });
  }

  salir(): void {
    this.api.salir();
    this.router.navigate(['/login']);
  }

  protected estado(valor: string): string {
    return ESTADOS[valor] ?? valor;
  }

  protected variable(factor: Factor): string {
    return VARIABLES[factor.variable] ?? factor.variable;
  }

  protected valor(valor: string | null): string {
    return valor === null ? '—' : (VALORES[valor] ?? valor);
  }

  protected tiempo(horas: string): string {
    const h = Number(horas);
    return h < 48 ? `${Math.round(h)} h` : `${Math.round(h / 24)} d`;
  }

  protected citas(justificacion: string): string[] {
    return justificacion.split(' | ').filter((c) => c.trim());
  }

  protected pesos(valor: number | null): string {
    return valor === null ? '—' : `$${valor.toLocaleString('es-CO')}`;
  }

  /** 7 → "7,0": con un decimal siempre, como en docs/validacion.md. */
  protected decimal(valor: number, decimales = 1): string {
    return valor.toLocaleString('es-CO', { minimumFractionDigits: decimales, maximumFractionDigits: decimales });
  }

  protected regla(nombre: string): string {
    return nombre.replace(/_/g, ' ');
  }

  private cargarCola(): void {
    this.cola.set(null);
    this.seleccionado.set(null);
    this.detalle.set(null);
    this.api.colaDelDia(this.asesorId()).subscribe({
      next: (c) => this.cola.set(c),
      error: (e) => this.mostrarError(e),
    });
  }

  private leadsDeCola(nombre: LeadCola['cola']): LeadCola[] {
    return this.cola()?.leads.filter((l) => l.cola === nombre) ?? [];
  }

  private mostrarError(e: HttpErrorResponse): void {
    if (e.status !== 401) this.error.set(e.error?.detail ?? 'Error al consultar la API');
  }
}
