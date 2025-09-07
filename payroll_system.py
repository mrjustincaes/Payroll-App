import uuid
import json
import sqlite3
import os
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Union
from enum import Enum
from datetime import datetime, date
from decimal import Decimal, ROUND_HALF_UP

# --- ENUMS AND CONSTANTS ---

class FilingStatus(Enum):
    SINGLE = "Single"
    MARRIED_JOINTLY = "Married Filing Jointly"
    MARRIED_SEPARATELY = "Married Filing Separately"
    HEAD_OF_HOUSEHOLD = "Head of Household"

class PayFrequency(Enum):
    WEEKLY = ("Weekly", 52)
    BI_WEEKLY = ("Bi-Weekly", 26)
    SEMI_MONTHLY = ("Semi-Monthly", 24)
    MONTHLY = ("Monthly", 12)
    
    def __init__(self, display_name: str, periods_per_year: int):
        self.display_name = display_name
        self.periods_per_year = periods_per_year

class State(Enum):
    TEXAS = ("TX", 0.0, 0)  # No state income tax
    CALIFORNIA = ("CA", 0.10, 5202)  # High tax state
    FLORIDA = ("FL", 0.0, 0)  # No state income tax
    NEW_YORK = ("NY", 0.085, 8000)  # High tax state
    COLORADO = ("CO", 0.045, 0)  # Flat tax state
    
    def __init__(self, code: str, max_rate: float, standard_deduction: int):
        self.code = code
        self.max_rate = max_rate
        self.standard_deduction = standard_deduction

# 2024 Federal Tax Brackets
FEDERAL_TAX_BRACKETS = {
    FilingStatus.SINGLE: [
        {"limit": 11600, "rate": 0.10},
        {"limit": 47150, "rate": 0.12},
        {"limit": 100525, "rate": 0.22},
        {"limit": 191950, "rate": 0.24},
        {"limit": 243725, "rate": 0.32},
        {"limit": 609350, "rate": 0.35},
        {"limit": float('inf'), "rate": 0.37}
    ],
    FilingStatus.MARRIED_JOINTLY: [
        {"limit": 23200, "rate": 0.10},
        {"limit": 94300, "rate": 0.12},
        {"limit": 201050, "rate": 0.22},
        {"limit": 383900, "rate": 0.24},
        {"limit": 487450, "rate": 0.32},
        {"limit": 731200, "rate": 0.35},
        {"limit": float('inf'), "rate": 0.37}
    ],
    FilingStatus.MARRIED_SEPARATELY: [
        {"limit": 11600, "rate": 0.10},
        {"limit": 47150, "rate": 0.12},
        {"limit": 100525, "rate": 0.22},
        {"limit": 191950, "rate": 0.24},
        {"limit": 243725, "rate": 0.32},
        {"limit": 365600, "rate": 0.35},
        {"limit": float('inf'), "rate": 0.37}
    ],
    FilingStatus.HEAD_OF_HOUSEHOLD: [
        {"limit": 16550, "rate": 0.10},
        {"limit": 63100, "rate": 0.12},
        {"limit": 100500, "rate": 0.22},
        {"limit": 191950, "rate": 0.24},
        {"limit": 243700, "rate": 0.32},
        {"limit": 609350, "rate": 0.35},
        {"limit": float('inf'), "rate": 0.37}
    ]
}

# 2024 Standard Deductions
STANDARD_DEDUCTIONS = {
    FilingStatus.SINGLE: 14600,
    FilingStatus.MARRIED_JOINTLY: 29200,
    FilingStatus.MARRIED_SEPARATELY: 14600,
    FilingStatus.HEAD_OF_HOUSEHOLD: 21900
}

# FICA Constants
SOCIAL_SECURITY_RATE = 0.062
MEDICARE_RATE = 0.0145
ADDITIONAL_MEDICARE_RATE = 0.009
SOCIAL_SECURITY_WAGE_BASE = 168600
ADDITIONAL_MEDICARE_THRESHOLD = 200000

# --- EXCEPTIONS ---
class PayrollError(Exception):
    """Base exception for payroll-related errors."""
    pass

class InvalidEmployeeDataError(PayrollError):
    """Raised when employee data is invalid."""
    pass

class DatabaseError(PayrollError):
    """Raised when database operations fail."""
    pass

# --- DATA MODELS ---

@dataclass
class PreTaxDeductions:
    """Represents pre-tax deductions."""
    health_insurance: float = 0.0
    dental_insurance: float = 0.0
    vision_insurance: float = 0.0
    retirement_401k: float = 0.0
    retirement_403b: float = 0.0
    hsa: float = 0.0
    fsa: float = 0.0
    parking: float = 0.0
    transit: float = 0.0
    life_insurance: float = 0.0
    
    def total(self) -> float:
        return sum([
            self.health_insurance, self.dental_insurance, self.vision_insurance,
            self.retirement_401k, self.retirement_403b, self.hsa, self.fsa,
            self.parking, self.transit, self.life_insurance
        ])

@dataclass
class PostTaxDeductions:
    """Represents post-tax deductions."""
    roth_401k: float = 0.0
    union_dues: float = 0.0
    charitable_contributions: float = 0.0
    garnishments: float = 0.0
    
    def total(self) -> float:
        return self.roth_401k + self.union_dues + self.charitable_contributions + self.garnishments

@dataclass
class Employee:
    """Base class for all employees."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    hire_date: str = field(default_factory=lambda: date.today().isoformat())
    is_active: bool = True
    is_w2: bool = True
    
    def __post_init__(self):
        if not self.name.strip():
            raise InvalidEmployeeDataError("Employee name cannot be empty")

@dataclass
class W2Employee(Employee):
    """Represents a W-2 employee with comprehensive tax information."""
    pay_rate: float = 0.0
    salary: float = 0.0  # Annual salary for salaried employees
    is_salaried: bool = False
    pay_frequency: PayFrequency = PayFrequency.BI_WEEKLY
    filing_status: FilingStatus = FilingStatus.SINGLE
    allowances: int = 0
    additional_withholding: float = 0.0  # Additional federal tax withholding
    state: State = State.TEXAS
    pre_tax_deductions: PreTaxDeductions = field(default_factory=PreTaxDeductions)
    post_tax_deductions: PostTaxDeductions = field(default_factory=PostTaxDeductions)
    is_exempt_from_federal: bool = False
    is_exempt_from_state: bool = False
    is_w2: bool = True
    
    def __post_init__(self):
        super().__post_init__()
        if not self.is_salaried and self.pay_rate <= 0:
            raise InvalidEmployeeDataError("Pay rate must be greater than 0 for hourly employees")
        if self.is_salaried and self.salary <= 0:
            raise InvalidEmployeeDataError("Salary must be greater than 0 for salaried employees")
        if self.allowances < 0:
            raise InvalidEmployeeDataError("Allowances cannot be negative")

@dataclass
class Contractor(Employee):
    """Represents a 1099 contractor."""
    pay_rate: float = 0.0
    is_w2: bool = False
    
    def __post_init__(self):
        super().__post_init__()
        if self.pay_rate <= 0:
            raise InvalidEmployeeDataError("Pay rate must be greater than 0")

@dataclass
class PayrollEntry:
    """Represents a single payroll entry."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    employee_id: str = ""
    pay_period_start: str = ""
    pay_period_end: str = ""
    pay_date: str = ""
    hours_worked: float = 0.0
    overtime_hours: float = 0.0
    gross_pay: float = 0.0
    pre_tax_deductions: float = 0.0
    taxable_income: float = 0.0
    federal_tax: float = 0.0
    social_security_tax: float = 0.0
    medicare_tax: float = 0.0
    additional_medicare_tax: float = 0.0
    state_tax: float = 0.0
    post_tax_deductions: float = 0.0
    total_deductions: float = 0.0
    net_pay: float = 0.0
    ytd_gross: float = 0.0
    ytd_federal_tax: float = 0.0
    ytd_social_security_tax: float = 0.0
    ytd_medicare_tax: float = 0.0
    ytd_state_tax: float = 0.0

# --- DATABASE MANAGER ---

class DatabaseManager:
    """Manages SQLite database operations for persistent storage."""
    
    def __init__(self, db_path: str = "payroll.db"):
        self.db_path = db_path
        self.init_database()
    
    def init_database(self):
        """Initialize the database with required tables."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Employees table
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS employees (
                        id TEXT PRIMARY KEY,
                        data TEXT NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                
                # Payroll entries table
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS payroll_entries (
                        id TEXT PRIMARY KEY,
                        employee_id TEXT NOT NULL,
                        pay_date TEXT NOT NULL,
                        data TEXT NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (employee_id) REFERENCES employees (id)
                    )
                ''')
                
                # YTD tracking table
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS ytd_earnings (
                        employee_id TEXT PRIMARY KEY,
                        year INTEGER NOT NULL,
                        gross_earnings REAL DEFAULT 0.0,
                        federal_tax_withheld REAL DEFAULT 0.0,
                        social_security_tax REAL DEFAULT 0.0,
                        medicare_tax_total REAL DEFAULT 0.0,
                        state_tax_withheld REAL DEFAULT 0.0,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (employee_id) REFERENCES employees (id)
                    )
                ''')
                
                conn.commit()
        except sqlite3.Error as e:
            raise DatabaseError(f"Failed to initialize database: {e}")
    
    def save_employee(self, employee: Employee):
        """Save or update an employee record."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                employee_data = json.dumps(asdict(employee), default=str)
                cursor.execute('''
                    INSERT OR REPLACE INTO employees (id, data, updated_at)
                    VALUES (?, ?, CURRENT_TIMESTAMP)
                ''', (employee.id, employee_data))
                conn.commit()
        except sqlite3.Error as e:
            raise DatabaseError(f"Failed to save employee: {e}")
    
    def load_employee(self, employee_id: str) -> Optional[Employee]:
        """Load an employee by ID."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT data FROM employees WHERE id = ?', (employee_id,))
                result = cursor.fetchone()
                
                if result:
                    employee_data = json.loads(result[0])
                    # Reconstruct the appropriate employee type
                    if employee_data.get('is_w2', True):
                        # Convert enum strings back to enum objects
                        if 'pay_frequency' in employee_data:
                            employee_data['pay_frequency'] = PayFrequency[employee_data['pay_frequency'].split('.')[1]]
                        if 'filing_status' in employee_data:
                            employee_data['filing_status'] = FilingStatus[employee_data['filing_status'].split('.')[1]]
                        if 'state' in employee_data:
                            employee_data['state'] = State[employee_data['state'].split('.')[1]]
                        
                        # Reconstruct nested objects
                        if 'pre_tax_deductions' in employee_data:
                            employee_data['pre_tax_deductions'] = PreTaxDeductions(**employee_data['pre_tax_deductions'])
                        if 'post_tax_deductions' in employee_data:
                            employee_data['post_tax_deductions'] = PostTaxDeductions(**employee_data['post_tax_deductions'])
                        
                        return W2Employee(**employee_data)
                    else:
                        return Contractor(**employee_data)
                return None
        except (sqlite3.Error, json.JSONDecodeError, KeyError) as e:
            raise DatabaseError(f"Failed to load employee: {e}")
    
    def load_all_employees(self) -> List[Employee]:
        """Load all employees from the database."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT id FROM employees WHERE 1=1')
                employee_ids = [row[0] for row in cursor.fetchall()]
                
                employees = []
                for emp_id in employee_ids:
                    employee = self.load_employee(emp_id)
                    if employee:
                        employees.append(employee)
                
                return employees
        except sqlite3.Error as e:
            raise DatabaseError(f"Failed to load employees: {e}")
    
    def save_payroll_entry(self, entry: PayrollEntry):
        """Save a payroll entry."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                entry_data = json.dumps(asdict(entry), default=str)
                cursor.execute('''
                    INSERT OR REPLACE INTO payroll_entries (id, employee_id, pay_date, data)
                    VALUES (?, ?, ?, ?)
                ''', (entry.id, entry.employee_id, entry.pay_date, entry_data))
                conn.commit()
        except sqlite3.Error as e:
            raise DatabaseError(f"Failed to save payroll entry: {e}")
    
    def update_ytd_earnings(self, employee_id: str, year: int, entry: PayrollEntry):
        """Update YTD earnings for an employee."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT OR REPLACE INTO ytd_earnings 
                    (employee_id, year, gross_earnings, federal_tax_withheld, 
                     social_security_tax, medicare_tax_total, state_tax_withheld, updated_at)
                    VALUES (?, ?, 
                            COALESCE((SELECT gross_earnings FROM ytd_earnings WHERE employee_id = ? AND year = ?), 0) + ?,
                            COALESCE((SELECT federal_tax_withheld FROM ytd_earnings WHERE employee_id = ? AND year = ?), 0) + ?,
                            COALESCE((SELECT social_security_tax FROM ytd_earnings WHERE employee_id = ? AND year = ?), 0) + ?,
                            COALESCE((SELECT medicare_tax_total FROM ytd_earnings WHERE employee_id = ? AND year = ?), 0) + ?,
                            COALESCE((SELECT state_tax_withheld FROM ytd_earnings WHERE employee_id = ? AND year = ?), 0) + ?,
                            CURRENT_TIMESTAMP)
                ''', (
                    employee_id, year,
                    employee_id, year, entry.gross_pay,
                    employee_id, year, entry.federal_tax,
                    employee_id, year, entry.social_security_tax,
                    employee_id, year, entry.medicare_tax + entry.additional_medicare_tax,
                    employee_id, year, entry.state_tax
                ))
                conn.commit()
        except sqlite3.Error as e:
            raise DatabaseError(f"Failed to update YTD earnings: {e}")
    
    def get_ytd_earnings(self, employee_id: str, year: int) -> Dict[str, float]:
        """Get YTD earnings for an employee."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT gross_earnings, federal_tax_withheld, social_security_tax,
                           medicare_tax_total, state_tax_withheld
                    FROM ytd_earnings
                    WHERE employee_id = ? AND year = ?
                ''', (employee_id, year))
                
                result = cursor.fetchone()
                if result:
                    return {
                        'gross_earnings': result[0],
                        'federal_tax_withheld': result[1],
                        'social_security_tax': result[2],
                        'medicare_tax_total': result[3],
                        'state_tax_withheld': result[4]
                    }
                return {
                    'gross_earnings': 0.0,
                    'federal_tax_withheld': 0.0,
                    'social_security_tax': 0.0,
                    'medicare_tax_total': 0.0,
                    'state_tax_withheld': 0.0
                }
        except sqlite3.Error as e:
            raise DatabaseError(f"Failed to get YTD earnings: {e}")

# --- ENHANCED PAYROLL CALCULATOR ---

class EnhancedPayrollCalculator:
    """Advanced payroll calculator with comprehensive tax scenarios."""
    
    def __init__(self):
        self.federal_tax_brackets = FEDERAL_TAX_BRACKETS
        self.standard_deductions = STANDARD_DEDUCTIONS
    
    def _round_currency(self, amount: float) -> float:
        """Round to nearest cent."""
        return float(Decimal(str(amount)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))
    
    def calculate_federal_withholding(self, taxable_income: float, filing_status: FilingStatus, 
                                    allowances: int, pay_frequency: PayFrequency, 
                                    additional_withholding: float = 0.0, 
                                    is_exempt: bool = False) -> float:
        """Enhanced federal tax withholding calculation."""
        if is_exempt:
            return 0.0
        
        # Annualize the taxable income
        annual_taxable = taxable_income * pay_frequency.periods_per_year
        
        # Subtract standard deduction
        standard_deduction = self.standard_deductions[filing_status]
        annual_taxable_after_deduction = max(0, annual_taxable - standard_deduction)
        
        # Subtract allowance amount (simplified calculation)
        allowance_amount = allowances * 4700  # 2024 allowance value
        annual_taxable_final = max(0, annual_taxable_after_deduction - allowance_amount)
        
        # Calculate annual tax
        annual_tax = self._calculate_tax_from_brackets(
            annual_taxable_final, 
            self.federal_tax_brackets[filing_status]
        )
        
        # Convert to per-paycheck withholding and add additional withholding
        per_paycheck_tax = annual_tax / pay_frequency.periods_per_year
        return self._round_currency(per_paycheck_tax + additional_withholding)
    
    def _calculate_tax_from_brackets(self, income: float, brackets: List[Dict]) -> float:
        """Calculate tax using progressive brackets."""
        tax = 0.0
        income_remaining = income
        previous_limit = 0
        
        for bracket in brackets:
            limit = bracket["limit"]
            rate = bracket["rate"]
            
            taxable_in_bracket = min(income_remaining, limit - previous_limit)
            tax += taxable_in_bracket * rate
            
            income_remaining -= taxable_in_bracket
            if income_remaining <= 0:
                break
            previous_limit = limit
        
        return tax
    
    def calculate_state_tax(self, taxable_income: float, state: State, 
                          filing_status: FilingStatus, pay_frequency: PayFrequency,
                          is_exempt: bool = False) -> float:
        """Enhanced state tax calculation."""
        if is_exempt or state.max_rate == 0:
            return 0.0
        
        # Simplified state tax calculation - in reality this would be much more complex
        annual_income = taxable_income * pay_frequency.periods_per_year
        state_taxable = max(0, annual_income - state.standard_deduction)
        
        # Apply a simplified progressive rate (this would vary significantly by state)
        if state == State.CALIFORNIA:
            # California has complex brackets - simplified here
            if state_taxable <= 20000:
                rate = 0.01
            elif state_taxable <= 50000:
                rate = 0.02
            elif state_taxable <= 100000:
                rate = 0.04
            else:
                rate = state.max_rate
        else:
            # Flat rate for other states
            rate = state.max_rate
        
        annual_state_tax = state_taxable * rate
        return self._round_currency(annual_state_tax / pay_frequency.periods_per_year)
    
    def calculate_fica_taxes(self, gross_pay: float, ytd_earnings: float) -> tuple[float, float, float]:
        """Enhanced FICA tax calculations."""
        # Social Security tax (capped)
        ss_taxable_earnings = min(gross_pay, max(0, SOCIAL_SECURITY_WAGE_BASE - ytd_earnings))
        ss_tax = self._round_currency(ss_taxable_earnings * SOCIAL_SECURITY_RATE)
        
        # Medicare tax (no cap)
        medicare_tax = self._round_currency(gross_pay * MEDICARE_RATE)
        
        # Additional Medicare tax (0.9% on wages over $200,000)
        additional_medicare_tax = 0.0
        if ytd_earnings + gross_pay > ADDITIONAL_MEDICARE_THRESHOLD:
            excess_wages = min(gross_pay, (ytd_earnings + gross_pay) - ADDITIONAL_MEDICARE_THRESHOLD)
            additional_medicare_tax = self._round_currency(excess_wages * ADDITIONAL_MEDICARE_RATE)
        
        return ss_tax, medicare_tax, additional_medicare_tax
    
    def calculate_gross_pay(self, employee: W2Employee, hours_worked: float, 
                           overtime_hours: float = 0.0) -> float:
        """Calculate gross pay including overtime."""
        if employee.is_salaried:
            # For salaried employees, calculate based on pay frequency
            return self._round_currency(employee.salary / employee.pay_frequency.periods_per_year)
        else:
            # Hourly employees
            regular_pay = hours_worked * employee.pay_rate
            overtime_pay = overtime_hours * employee.pay_rate * 1.5  # Time and a half
            return self._round_currency(regular_pay + overtime_pay)
    
    def process_w2_payroll(self, employee: W2Employee, hours_worked: float, 
                          overtime_hours: float = 0.0, ytd_data: Dict = None) -> PayrollEntry:
        """Process comprehensive W-2 payroll."""
        if hours_worked < 0 or overtime_hours < 0:
            raise PayrollError("Hours cannot be negative")
        
        if ytd_data is None:
            ytd_data = {'gross_earnings': 0.0}
        
        # Calculate gross pay
        gross_pay = self.calculate_gross_pay(employee, hours_worked, overtime_hours)
        
        # Pre-tax deductions
        pre_tax_total = self._round_currency(employee.pre_tax_deductions.total())
        
        # Taxable income after pre-tax deductions
        taxable_income = max(0, gross_pay - pre_tax_total)
        
        # Calculate taxes
        federal_tax = self.calculate_federal_withholding(
            taxable_income, employee.filing_status, employee.allowances,
            employee.pay_frequency, employee.additional_withholding,
            employee.is_exempt_from_federal
        )
        
        ss_tax, medicare_tax, additional_medicare_tax = self.calculate_fica_taxes(
            gross_pay, ytd_data['gross_earnings']
        )
        
        state_tax = self.calculate_state_tax(
            taxable_income, employee.state, employee.filing_status,
            employee.pay_frequency, employee.is_exempt_from_state
        )
        
        # Post-tax deductions
        post_tax_total = self._round_currency(employee.post_tax_deductions.total())
        
        # Calculate totals
        total_tax_deductions = federal_tax + ss_tax + medicare_tax + additional_medicare_tax + state_tax
        total_deductions = pre_tax_total + total_tax_deductions + post_tax_total
        net_pay = self._round_currency(gross_pay - total_deductions)
        
        # Create payroll entry
        today = date.today().isoformat()
        entry = PayrollEntry(
            employee_id=employee.id,
            pay_period_start=today,
            pay_period_end=today,
            pay_date=today,
            hours_worked=hours_worked,
            overtime_hours=overtime_hours,
            gross_pay=gross_pay,
            pre_tax_deductions=pre_tax_total,
            taxable_income=taxable_income,
            federal_tax=federal_tax,
            social_security_tax=ss_tax,
            medicare_tax=medicare_tax,
            additional_medicare_tax=additional_medicare_tax,
            state_tax=state_tax,
            post_tax_deductions=post_tax_total,
            total_deductions=total_deductions,
            net_pay=net_pay,
            ytd_gross=ytd_data['gross_earnings'] + gross_pay
        )
        
        return entry

# --- REPORT GENERATOR ---

class ReportGenerator:
    """Generates detailed payroll reports and tax forms."""
    
    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager
    
    def generate_paystub_report(self, entry: PayrollEntry, employee: Employee) -> str:
        """Generate a detailed paystub report."""
        report = f"""
{'='*60}
                    EMPLOYEE PAYSTUB
{'='*60}
Employee: {employee.name}
Employee ID: {employee.id[:8]}...
Pay Period: {entry.pay_period_start} to {entry.pay_period_end}
Pay Date: {entry.pay_date}

{'='*60}
                    EARNINGS
{'='*60}
Regular Hours: {entry.hours_worked:>10.2f}
Overtime Hours: {entry.overtime_hours:>9.2f}
Gross Pay: ${entry.gross_pay:>15,.2f}

{'='*60}
                PRE-TAX DEDUCTIONS
{'='*60}
"""
        
        if isinstance(employee, W2Employee):
            deductions = employee.pre_tax_deductions
            if deductions.health_insurance > 0:
                report += f"Health Insurance: ${deductions.health_insurance:>10,.2f}\n"
            if deductions.dental_insurance > 0:
                report += f"Dental Insurance: ${deductions.dental_insurance:>10,.2f}\n"
            if deductions.vision_insurance > 0:
                report += f"Vision Insurance: ${deductions.vision_insurance:>10,.2f}\n"
            if deductions.retirement_401k > 0:
                report += f"401(k): ${deductions.retirement_401k:>19,.2f}\n"
            if deductions.hsa > 0:
                report += f"HSA: ${deductions.hsa:>23,.2f}\n"
            
            report += f"""
Total Pre-Tax Deductions: ${entry.pre_tax_deductions:>8,.2f}
Taxable Income: ${entry.taxable_income:>17,.2f}

{'='*60}
                  TAX WITHHOLDINGS
{'='*60}
Federal Income Tax: ${entry.federal_tax:>13,.2f}
Social Security Tax: ${entry.social_security_tax:>12,.2f}
Medicare Tax: ${entry.medicare_tax:>17,.2f}"""
            
            if entry.additional_medicare_tax > 0:
                report += f"\nAdditional Medicare Tax: ${entry.additional_medicare_tax:>7,.2f}"
            
            report += f"\nState Income Tax: ${entry.state_tax:>15,.2f}"
            
            # Post-tax deductions
            post_tax = employee.post_tax_deductions
            if post_tax.total() > 0:
                report += f"""

{'='*60}
               POST-TAX DEDUCTIONS
{'='*60}"""
                if post_tax.roth_401k > 0:
                    report += f"\nRoth 401(k): ${post_tax.roth_401k:>16,.2f}"
                if post_tax.union_dues > 0:
                    report += f"\nUnion Dues: ${post_tax.union_dues:>17,.2f}"
        
        report += f"""

{'='*60}
                     SUMMARY
{'='*60}
Total Deductions: ${entry.total_deductions:>15,.2f}
NET PAY: ${entry.net_pay:>23,.2f}

YTD Gross Earnings: ${entry.ytd_gross:>13,.2f}
{'='*60}
"""
        
        return report
    
    def generate_w2_form(self, employee: W2Employee, year: int) -> str:
        """Generate a simplified W-2 form."""
        ytd_data = self.db.get_ytd_earnings(employee.id, year)
        
        w2_form = f"""
{'='*70}
                        FORM W-2 (Simplified)
                    Wage and Tax Statement - {year}
{'='*70}

EMPLOYER INFORMATION:
Your Company Name
123 Business Street
