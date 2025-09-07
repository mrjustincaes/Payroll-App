import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Union

# --- 2024 TAX CONSTANTS ---
# Using simplified federal tax brackets for a Single filer, for demonstration purposes.
# This assumes an individual is taking the standard deduction.
# Real-world systems would need to handle all filing statuses and deductions.
FEDERAL_TAX_BRACKETS = [
    {"limit": 11600, "rate": 0.10},
    {"limit": 47150, "rate": 0.12},
    {"limit": 100525, "rate": 0.22},
    {"limit": 191950, "rate": 0.24},
    {"limit": 243725, "rate": 0.32},
    {"limit": 609350, "rate": 0.35},
    {"limit": float('inf'), "rate": 0.37}
]

# FICA tax rates for 2024
SOCIAL_SECURITY_RATE = 0.062
MEDICARE_RATE = 0.0145
SOCIAL_SECURITY_WAGE_BASE = 168600

# --- DATA MODELS ---
# These dataclasses act as the data models for our system.
# They are a great modern alternative to simple dictionaries.

@dataclass
class Employee:
    """Base class for all employees and contractors."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    is_w2: bool  # True for W-2, False for 1099
    pay_rate: float
    pay_history: List[Dict] = field(default_factory=list)
    ytd_gross_pay: float = 0.0
    ytd_tax_withheld: float = 0.0

@dataclass
class W2Employee(Employee):
    """Represents a W-2 employee with tax-specific information."""
    filing_status: str
    allowances: int
    state_tax_rate: float = 0.03  # Example flat rate for demonstration (e.g., CA)
    is_w2: bool = True

@dataclass
class Contractor(Employee):
    """Represents a 1099 contractor."""
    is_w2: bool = False

# --- PAYROLL PROCESSING LOGIC ---
# This class contains all the business logic for calculating payroll.

class PayrollCalculator:
    """
    Calculates federal, FICA, and state taxes, and processes payroll
    for W-2 employees and 1099 contractors.
    """
    def __init__(self):
        self.federal_tax_brackets = FEDERAL_TAX_BRACKETS
        self.fica_social_security_rate = SOCIAL_SECURITY_RATE
        self.fica_medicare_rate = MEDICARE_RATE
        self.social_security_wage_base = SOCIAL_SECURITY_WAGE_BASE

    def calculate_federal_income_tax(self, taxable_income: float) -> float:
        """
        Calculates federal income tax based on 2024 tax brackets.
        This is a progressive tax calculation.
        """
        tax = 0.0
        income_remaining = taxable_income
        previous_limit = 0
        
        for bracket in self.federal_tax_brackets:
            limit = bracket["limit"]
            rate = bracket["rate"]
            
            # Calculate the portion of income falling within the current bracket
            taxable_in_bracket = min(income_remaining, limit - previous_limit)
            tax += taxable_in_bracket * rate
            
            income_remaining -= taxable_in_bracket
            if income_remaining <= 0:
                break
            previous_limit = limit
            
        return tax

    def calculate_fica_taxes(self, gross_pay: float, ytd_earnings: float) -> tuple[float, float]:
        """
        Calculates Social Security and Medicare taxes.
        Social Security has a wage base limit.
        """
        # Social Security is only calculated on earnings up to the wage base.
        ss_taxable_earnings = min(gross_pay, max(0, self.social_security_wage_base - ytd_earnings))
        ss_tax = ss_taxable_earnings * self.fica_social_security_rate
        
        # Medicare has no wage base limit and is applied to all gross pay.
        medicare_tax = gross_pay * self.fica_medicare_rate
        
        return ss_tax, medicare_tax

    def calculate_state_tax(self, taxable_income: float, state_rate: float) -> float:
        """
        A simplified state tax calculation using a flat rate.
        This framework can be extended to handle state-specific brackets.
        """
        return taxable_income * state_rate

    def process_w2_payroll(self, employee: W2Employee, hours_worked: float):
        """Processes payroll for a W-2 employee, calculating all taxes."""
        gross_pay = hours_worked * employee.pay_rate
        
        # For simplicity, we assume no pre-tax deductions like 401k or health insurance.
        taxable_income = gross_pay
        
        # Calculate all required taxes
        federal_tax = self.calculate_federal_income_tax(taxable_income)
        ss_tax, medicare_tax = self.calculate_fica_taxes(gross_pay, employee.ytd_gross_pay)
        state_tax = self.calculate_state_tax(taxable_income, employee.state_tax_rate)
        
        # Sum up all deductions and calculate net pay
        total_deductions = federal_tax + ss_tax + medicare_tax + state_tax
        net_pay = gross_pay - total_deductions
        
        # Update employee's year-to-date totals
        employee.ytd_gross_pay += gross_pay
        employee.ytd_tax_withheld += total_deductions
        
        # Return a dictionary representing the paystub for this period
        return {
            "gross_pay": round(gross_pay, 2),
            "federal_tax": round(federal_tax, 2),
            "social_security_tax": round(ss_tax, 2),
            "medicare_tax": round(medicare_tax, 2),
            "state_tax": round(state_tax, 2),
            "total_deductions": round(total_deductions, 2),
            "net_pay": round(net_pay, 2)
        }
    
    def process_1099_payroll(self, contractor: Contractor, hours_worked: float):
        """Processes payroll for a 1099 contractor (no taxes withheld)."""
        gross_pay = hours_worked * contractor.pay_rate
        contractor.ytd_gross_pay += gross_pay
        
        # No taxes are withheld from a 1099 contractor's pay.
        # They are responsible for paying their own self-employment taxes.
        return {
            "gross_pay": round(gross_pay, 2),
            "net_pay": round(gross_pay, 2)
        }

# --- DEMONSTRATION & SIMPLE REPORTING ---
# This section demonstrates how to use the payroll system.

def run_payroll_demo():
    """Main function to run the payroll system demonstration and generate reports."""
    print("--- Payroll System Demo ---")
    
    # In-memory "database" to hold employee data
    employees: List[Employee] = [
        W2Employee(name="Jane Doe", pay_rate=35.00, filing_status="Single", allowances=0),
        Contractor(name="John Smith", pay_rate=75.00)
    ]
    
    payroll_calc = PayrollCalculator()
    
    # Process Jane's pay (W-2) for a payroll period
    jane = employees[0]
    hours_jane = 40
    print(f"\nProcessing payroll for {jane.name} (W-2) for {hours_jane} hours...")
    paystub_jane = payroll_calc.process_w2_payroll(jane, hours_jane)
    jane.pay_history.append(paystub_jane)
    
    # Display the paystub
    print("\n--- PAYSTUB: Jane Doe ---")
    print(f"Gross Pay: ${paystub_jane['gross_pay']:,}")
    print("--- Deductions ---")
    print(f"Federal Tax: ${paystub_jane['federal_tax']:,}")
    print(f"Social Security: ${paystub_jane['social_security_tax']:,}")
    print(f"Medicare: ${paystub_jane['medicare_tax']:,}")
    print(f"State Tax: ${paystub_jane['state_tax']:,}")
    print(f"Total Deductions: ${paystub_jane['total_deductions']:,}")
    print(f"Net Pay: ${paystub_jane['net_pay']:,}")
    
    # Process John's pay (1099)
    john = employees[1]
    hours_john = 25
    print(f"\n\nProcessing payroll for {john.name} (1099) for {hours_john} hours...")
    paystub_john = payroll_calc.process_1099_payroll(john, hours_john)
    john.pay_history.append(paystub_john)
    
    # Display the paystub
    print("\n--- PAYSTUB: John Smith ---")
    print(f"Gross Pay: ${paystub_john['gross_pay']:,}")
    print(f"Net Pay: ${paystub_john['net_pay']:,}")
    print("\nNote: No taxes are withheld from a 1099 contractor's pay.")

    # Simple Reporting
    print("\n" + "="*40)
    print("  SIMPLE REPORTS")
    print("="*40)
    print("\n-- YTD Summary for Jane Doe --")
    print(f"Total Gross Pay: ${jane.ytd_gross_pay:,}")
    print(f"Total Taxes Withheld: ${jane.ytd_tax_withheld:,}")

    print("\n-- YTD Summary for John Smith --")
    print(f"Total Gross Pay: ${john.ytd_gross_pay:,}")
    print(f"Total Taxes Withheld: ${john.ytd_tax_withheld:,}")

if __name__ == "__main__":
    run_payroll_demo()
