import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Union
from enum import Enum

# --- 2024 TAX CONSTANTS ---
class FilingStatus(Enum):
    SINGLE = "Single"
    MARRIED_JOINTLY = "Married Filing Jointly"
    MARRIED_SEPARATELY = "Married Filing Separately"
    HEAD_OF_HOUSEHOLD = "Head of Household"

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
    ]
}

# 2024 Standard Deductions
STANDARD_DEDUCTIONS = {
    FilingStatus.SINGLE: 14600,
    FilingStatus.MARRIED_JOINTLY: 29200,
    FilingStatus.MARRIED_SEPARATELY: 14600,
    FilingStatus.HEAD_OF_HOUSEHOLD: 21900
}

# FICA tax rates and limits
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

# --- DATA MODELS ---

@dataclass
class PreTaxDeductions:
    """Represents pre-tax deductions."""
    health_insurance: float = 0.0
    dental_insurance: float = 0.0
    retirement_401k: float = 0.0
    hsa: float = 0.0
    
    def total(self) -> float:
        return self.health_insurance + self.dental_insurance + self.retirement_401k + self.hsa

@dataclass
class Employee:
    """Base class for all employees."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    is_w2: bool = True
    
    def __post_init__(self):
        if not self.name.strip():
            raise InvalidEmployeeDataError("Employee name cannot be empty")

@dataclass
class W2Employee(Employee):
    """Represents a W-2 employee with tax information."""
    pay_rate: float = 0.0
    filing_status: FilingStatus = FilingStatus.SINGLE
    allowances: int = 0
    state_tax_rate: float = 0.0
    pre_tax_deductions: PreTaxDeductions = field(default_factory=PreTaxDeductions)
    is_w2: bool = True
    
    def __post_init__(self):
        super().__post_init__()
        if self.pay_rate <= 0:
            raise InvalidEmployeeDataError("Pay rate must be greater than 0")
        if self.allowances < 0:
            raise InvalidEmployeeDataError("Allowances cannot be negative")
        if self.state_tax_rate < 0 or self.state_tax_rate > 1:
            raise InvalidEmployeeDataError("State tax rate must be between 0 and 1")

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
class PaystubResult:
    """Represents the result of a payroll calculation."""
    employee_name: str
    employee_type: str
    hours_worked: float
    gross_pay: float
    pre_tax_deductions: float = 0.0
    taxable_income: float = 0.0
    federal_tax: float = 0.0
    social_security_tax: float = 0.0
    medicare_tax: float = 0.0
    additional_medicare_tax: float = 0.0
    state_tax: float = 0.0
    total_deductions: float = 0.0
    net_pay: float = 0.0

# --- PAYROLL PROCESSING LOGIC ---

class PayrollCalculator:
    """Enhanced payroll calculator with improved accuracy and features."""
    
    def __init__(self):
        self.federal_tax_brackets = FEDERAL_TAX_BRACKETS
        self.standard_deductions = STANDARD_DEDUCTIONS
        self.fica_social_security_rate = SOCIAL_SECURITY_RATE
        self.fica_medicare_rate = MEDICARE_RATE
        self.additional_medicare_rate = ADDITIONAL_MEDICARE_RATE
        self.social_security_wage_base = SOCIAL_SECURITY_WAGE_BASE
        self.additional_medicare_threshold = ADDITIONAL_MEDICARE_THRESHOLD

    def calculate_federal_withholding(self, taxable_income: float, filing_status: FilingStatus, 
                                    allowances: int) -> float:
        """
        Calculates federal income tax withholding using simplified percentage method.
        This is an approximation - actual payroll systems use IRS Publication 15 tables.
        """
        # Get annual taxable income (assuming bi-weekly pay)
        annual_taxable = taxable_income * 26
        
        # Subtract standard deduction
        standard_deduction = self.standard_deductions[filing_status]
        annual_taxable_after_deduction = max(0, annual_taxable - standard_deduction)
        
        # Subtract allowance amount (simplified - $4,700 per allowance for 2024)
        allowance_amount = allowances * 4700
        annual_taxable_final = max(0, annual_taxable_after_deduction - allowance_amount)
        
        # Calculate annual tax
        annual_tax = self._calculate_tax_from_brackets(
            annual_taxable_final, 
            self.federal_tax_brackets[filing_status]
        )
        
        # Return per-paycheck withholding
        return annual_tax / 26

    def _calculate_tax_from_brackets(self, income: float, brackets: List[Dict]) -> float:
        """Calculates tax using progressive tax brackets."""
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

    def calculate_fica_taxes(self, gross_pay: float, ytd_earnings: float) -> tuple[float, float, float]:
        """Calculates Social Security, Medicare, and Additional Medicare taxes."""
        # Social Security tax (capped at wage base)
        ss_taxable_earnings = min(gross_pay, max(0, self.social_security_wage_base - ytd_earnings))
        ss_tax = ss_taxable_earnings * self.fica_social_security_rate
        
        # Medicare tax (no wage base limit)
        medicare_tax = gross_pay * self.fica_medicare_rate
        
        # Additional Medicare tax (0.9% on wages over $200,000)
        additional_medicare_tax = 0.0
        if ytd_earnings + gross_pay > self.additional_medicare_threshold:
            excess_wages = min(gross_pay, (ytd_earnings + gross_pay) - self.additional_medicare_threshold)
            additional_medicare_tax = excess_wages * self.additional_medicare_rate
        
        return ss_tax, medicare_tax, additional_medicare_tax

    def calculate_state_tax(self, taxable_income: float, state_rate: float) -> float:
        """Simplified state tax calculation."""
        return taxable_income * state_rate

    def process_w2_payroll(self, employee: W2Employee, hours_worked: float, 
                          ytd_earnings: float = 0.0) -> PaystubResult:
        """Processes payroll for a W-2 employee with enhanced calculations."""
        if hours_worked < 0:
            raise PayrollError("Hours worked cannot be negative")
        
        gross_pay = hours_worked * employee.pay_rate
        
        # Calculate pre-tax deductions
        pre_tax_total = employee.pre_tax_deductions.total()
        
        # Taxable income after pre-tax deductions
        taxable_income = max(0, gross_pay - pre_tax_total)
        
        # Calculate taxes
        federal_tax = self.calculate_federal_withholding(
            taxable_income, employee.filing_status, employee.allowances
        )
        ss_tax, medicare_tax, additional_medicare_tax = self.calculate_fica_taxes(
            gross_pay, ytd_earnings
        )
        state_tax = self.calculate_state_tax(taxable_income, employee.state_tax_rate)
        
        # Calculate totals
        total_tax_deductions = federal_tax + ss_tax + medicare_tax + additional_medicare_tax + state_tax
        total_deductions = pre_tax_total + total_tax_deductions
        net_pay = gross_pay - total_deductions
        
        return PaystubResult(
            employee_name=employee.name,
            employee_type="W-2 Employee",
            hours_worked=hours_worked,
            gross_pay=round(gross_pay, 2),
            pre_tax_deductions=round(pre_tax_total, 2),
            taxable_income=round(taxable_income, 2),
            federal_tax=round(federal_tax, 2),
            social_security_tax=round(ss_tax, 2),
            medicare_tax=round(medicare_tax, 2),
            additional_medicare_tax=round(additional_medicare_tax, 2),
            state_tax=round(state_tax, 2),
            total_deductions=round(total_deductions, 2),
            net_pay=round(net_pay, 2)
        )
    
    def process_1099_payroll(self, contractor: Contractor, hours_worked: float) -> PaystubResult:
        """Processes payroll for a 1099 contractor."""
        if hours_worked < 0:
            raise PayrollError("Hours worked cannot be negative")
            
        gross_pay = hours_worked * contractor.pay_rate
        
        return PaystubResult(
            employee_name=contractor.name,
            employee_type="1099 Contractor",
            hours_worked=hours_worked,
            gross_pay=round(gross_pay, 2),
            net_pay=round(gross_pay, 2)
        )

# --- PAYROLL SYSTEM ---

class PayrollSystem:
    """Main payroll system class that manages employees and processes payroll."""
    
    def __init__(self):
        self.employees: Dict[str, Employee] = {}
        self.calculator = PayrollCalculator()
        self.ytd_earnings: Dict[str, float] = {}  # Track YTD earnings by employee ID
    
    def add_employee(self, employee: Employee) -> str:
        """Adds an employee to the system."""
        self.employees[employee.id] = employee
        self.ytd_earnings[employee.id] = 0.0
        return employee.id
    
    def get_employee(self, employee_id: str) -> Optional[Employee]:
        """Retrieves an employee by ID."""
        return self.employees.get(employee_id)
    
    def list_employees(self) -> List[Employee]:
        """Returns a list of all employees."""
        return list(self.employees.values())
    
    def process_payroll(self, employee_id: str, hours_worked: float) -> PaystubResult:
        """Processes payroll for a specific employee."""
        employee = self.get_employee(employee_id)
        if not employee:
            raise PayrollError(f"Employee with ID {employee_id} not found")
        
        ytd = self.ytd_earnings.get(employee_id, 0.0)
        
        if isinstance(employee, W2Employee):
            result = self.calculator.process_w2_payroll(employee, hours_worked, ytd)
        elif isinstance(employee, Contractor):
            result = self.calculator.process_1099_payroll(employee, hours_worked)
        else:
            raise PayrollError(f"Unknown employee type: {type(employee)}")
        
        # Update YTD earnings
        self.ytd_earnings[employee_id] += result.gross_pay
        
        return result

def print_paystub(result: PaystubResult):
    """Prints a formatted paystub."""
    print(f"\n{'='*50}")
    print(f"PAYSTUB: {result.employee_name} ({result.employee_type})")
    print(f"{'='*50}")
    print(f"Hours Worked: {result.hours_worked}")
    print(f"Gross Pay: ${result.gross_pay:,.2f}")
    
    if result.employee_type == "W-2 Employee":
        print(f"\nPre-Tax Deductions: ${result.pre_tax_deductions:,.2f}")
        print(f"Taxable Income: ${result.taxable_income:,.2f}")
        print(f"\n--- TAX WITHHOLDINGS ---")
        print(f"Federal Tax: ${result.federal_tax:,.2f}")
        print(f"Social Security: ${result.social_security_tax:,.2f}")
        print(f"Medicare: ${result.medicare_tax:,.2f}")
        if result.additional_medicare_tax > 0:
            print(f"Additional Medicare: ${result.additional_medicare_tax:,.2f}")
        print(f"State Tax: ${result.state_tax:,.2f}")
        print(f"\nTotal Deductions: ${result.total_deductions:,.2f}")
    else:
        print("\nNote: No taxes withheld. Contractor responsible for own taxes.")
    
    print(f"\nNET PAY: ${result.net_pay:,.2f}")
    print(f"{'='*50}")

# --- INTERACTIVE DEMO ---

def run_interactive_demo():
    """Interactive demonstration of the payroll system."""
    print("🏢 Enhanced Payroll System Demo")
    print("="*40)
    
    system = PayrollSystem()
    
    try:
        # Create sample employees
        jane = W2Employee(
            name="Jane Doe",
            pay_rate=35.00,
            filing_status=FilingStatus.SINGLE,
            allowances=1,
            state_tax_rate=0.05,
            pre_tax_deductions=PreTaxDeductions(
                health_insurance=150.00,
                retirement_401k=200.00,
                hsa=50.00
            )
        )
        
        john = Contractor(
            name="John Smith",
            pay_rate=75.00
        )
        
        # High earner to demonstrate additional Medicare tax
        sarah = W2Employee(
            name="Sarah Johnson",
            pay_rate=200.00,
            filing_status=FilingStatus.MARRIED_JOINTLY,
            allowances=2,
            state_tax_rate=0.08,
            pre_tax_deductions=PreTaxDeductions(
                health_insurance=300.00,
                retirement_401k=1000.00
            )
        )
        
        # Add employees to system
        jane_id = system.add_employee(jane)
        john_id = system.add_employee(john)
        sarah_id = system.add_employee(sarah)
        
        # Set some YTD earnings to demonstrate caps
        system.ytd_earnings[sarah_id] = 150000  # High YTD to show additional Medicare tax
        
        print(f"Added {len(system.employees)} employees to the system\n")
        
        # Process payroll for different scenarios
        test_cases = [
            (jane_id, 40, "Regular full-time week"),
            (john_id, 25, "Contractor hours"),
            (sarah_id, 40, "High earner (demonstrates additional Medicare tax)"),
            (jane_id, 50, "Overtime week")
        ]
        
        for employee_id, hours, description in test_cases:
            print(f"\n📊 Processing: {description}")
            result = system.process_payroll(employee_id, hours)
            print_paystub(result)
            
            # Show updated YTD
            employee = system.get_employee(employee_id)
            ytd = system.ytd_earnings[employee_id]
            print(f"Updated YTD Earnings: ${ytd:,.2f}")
        
        print(f"\n✅ Demo completed successfully!")
        print(f"Total employees processed: {len(system.employees)}")
        
    except (PayrollError, InvalidEmployeeDataError) as e:
        print(f"❌ Error: {e}")
    except Exception as e:
        print(f"❌ Unexpected error: {e}")

def run_quick_test():
    """Quick test function for basic validation."""
    print("🧪 Running Quick Tests...")
    
    try:
        # Test basic functionality
        calc = PayrollCalculator()
        
        # Test W2 employee
        employee = W2Employee(
            name="Test Employee",
            pay_rate=25.00,
            filing_status=FilingStatus.SINGLE,
            allowances=0,
            state_tax_rate=0.06
        )
        
        result = calc.process_w2_payroll(employee, 40)
        assert result.gross_pay == 1000.00, f"Expected gross pay 1000.00, got {result.gross_pay}"
        assert result.net_pay < result.gross_pay, "Net pay should be less than gross pay"
        
        # Test contractor
        contractor = Contractor(name="Test Contractor", pay_rate=50.00)
        result = calc.process_1099_payroll(contractor, 20)
        assert result.gross_pay == 1000.00, f"Expected gross pay 1000.00, got {result.gross_pay}"
        assert result.net_pay == result.gross_pay, "Contractor net pay should equal gross pay"
        
        print("✅ All tests passed!")
        
    except Exception as e:
        print(f"❌ Test failed: {e}")

if __name__ == "__main__":
    # You can run either the interactive demo or quick tests
    print("Choose an option:")
    print("1. Run Interactive Demo")
    print("2. Run Quick Tests")
    print("3. Run Both")
    
    choice = input("Enter choice (1-3): ").strip()
    
    if choice == "1":
        run_interactive_demo()
    elif choice == "2":
        run_quick_test()
    elif choice == "3":
        run_quick_test()
        print("\n" + "="*60 + "\n")
        run_interactive_demo()
    else:
        print("Invalid choice. Running interactive demo...")
        run_interactive_demo()
