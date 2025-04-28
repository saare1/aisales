import logging
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from sqlalchemy import func, desc
from sqlalchemy.orm import Session

from app.db.database import get_db_session
from app.db.models import Lead, Conversation, LeadStatus, ScheduledAction, BusinessConfiguration, ObjectionType, DetectedObjection
from app.services.messaging import MessagingService

# Configure logging
logger = logging.getLogger(__name__)


class ReportType:
    """Constants for report types."""
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    CUSTOM = "custom"


class ReportFormat:
    """Constants for report formats."""
    TEXT = "text"
    HTML = "html"
    JSON = "json"


class ReportGenerator:
    """
    Service for generating automated reports on sales activity and performance.
    """
    
    @classmethod
    def generate_activity_report(
        cls,
        report_type: str = ReportType.DAILY,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        business_id: Optional[int] = None,
        include_lead_details: bool = False,
        format_type: str = ReportFormat.TEXT,
        db: Session = None
    ) -> Dict[str, Any]:
        """
        Generate a report on sales activity for a specified time period.
        
        Args:
            report_type: Type of report (daily, weekly, monthly, custom)
            start_date: Start date for the report period (defaults to based on report_type)
            end_date: End date for the report period (defaults to current time)
            business_id: Optional business ID to filter data
            include_lead_details: Whether to include details for each lead
            format_type: Format of the report (text, html, json)
            db: Database session
            
        Returns:
            Dictionary with report data
        """
        close_db = False
        if db is None:
            db = get_db_session()
            close_db = True
        
        try:
            # Set default end date to now
            if end_date is None:
                end_date = datetime.utcnow()
                
            # Set default start date based on report type
            if start_date is None:
                if report_type == ReportType.DAILY:
                    start_date = end_date - timedelta(days=1)
                elif report_type == ReportType.WEEKLY:
                    start_date = end_date - timedelta(days=7)
                elif report_type == ReportType.MONTHLY:
                    start_date = end_date - timedelta(days=30)
                else:  # Custom or unknown
                    start_date = end_date - timedelta(days=1)  # Default to daily
            
            # Get report data
            metrics = cls._get_activity_metrics(start_date, end_date, business_id, db)
            
            # Get lead details if requested
            leads_data = []
            if include_lead_details:
                leads_data = cls._get_lead_details(start_date, end_date, business_id, db)
            
            # Build the report
            report_data = {
                "report_type": report_type,
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "generated_at": datetime.utcnow().isoformat(),
                "business_id": business_id,
                "metrics": metrics,
                "leads": leads_data if include_lead_details else []
            }
            
            # Format the report
            if format_type == ReportFormat.TEXT:
                report = cls._format_text_report(report_data)
            elif format_type == ReportFormat.HTML:
                report = cls._format_html_report(report_data)
            else:  # Default to JSON
                report = report_data
            
            # Store the report (if needed)
            # This could be extended to save the report to the database
            
            return report
        finally:
            if close_db:
                db.close()
    
    @classmethod
    def _get_activity_metrics(
        cls,
        start_date: datetime,
        end_date: datetime,
        business_id: Optional[int],
        db: Session
    ) -> Dict[str, Any]:
        """
        Get metrics for the activity report.
        
        Args:
            start_date: Start date for the report period
            end_date: End date for the report period
            business_id: Optional business ID to filter data
            db: Database session
            
        Returns:
            Dictionary with activity metrics
        """
        # Base query filter for time period
        period_filter = [
            Lead.created_at.between(start_date, end_date) | 
            Lead.updated_at.between(start_date, end_date) |
            Lead.last_contact.between(start_date, end_date)
        ]
        
        # Add business filter if provided
        if business_id is not None:
            period_filter.append(Lead.business_id == business_id)
        
        # Count new leads
        new_leads_count = db.query(func.count(Lead.id)).filter(
            Lead.created_at.between(start_date, end_date),
            *period_filter
        ).scalar() or 0
        
        # Count leads by status
        leads_by_status = {}
        for status in LeadStatus:
            count = db.query(func.count(Lead.id)).filter(
                Lead.status == status,
                *period_filter
            ).scalar() or 0
            leads_by_status[status.value] = count
        
        # Count meetings scheduled
        meetings_scheduled = db.query(func.count(ScheduledAction.id)).filter(
            ScheduledAction.action_type == "meeting",
            ScheduledAction.created_at.between(start_date, end_date),
            *period_filter
        ).scalar() or 0
        
        # Count follow-ups scheduled
        followups_scheduled = db.query(func.count(ScheduledAction.id)).filter(
            ScheduledAction.action_type == "followup",
            ScheduledAction.created_at.between(start_date, end_date),
            *period_filter
        ).scalar() or 0
        
        # Count closed sales (leads moved to won status)
        closed_sales = db.query(func.count(Lead.id)).filter(
            Lead.status == LeadStatus.WON,
            Lead.updated_at.between(start_date, end_date),
            *period_filter
        ).scalar() or 0
        
        # Count conversations
        conversation_count = db.query(func.count(Conversation.id)).filter(
            Conversation.created_at.between(start_date, end_date),
            *period_filter
        ).scalar() or 0
        
        # Get top objections
        top_objections = cls._get_top_objections(start_date, end_date, business_id, db)
        
        return {
            "new_leads": new_leads_count,
            "leads_by_status": leads_by_status,
            "meetings_scheduled": meetings_scheduled,
            "followups_scheduled": followups_scheduled,
            "closed_sales": closed_sales,
            "conversation_count": conversation_count,
            "top_objections": top_objections
        }
    
    @classmethod
    def _get_top_objections(
        cls,
        start_date: datetime,
        end_date: datetime,
        business_id: Optional[int],
        db: Session
    ) -> List[Dict[str, Any]]:
        """
        Get the top objections raised by leads.
        
        Args:
            start_date: Start date for the report period
            end_date: End date for the report period
            business_id: Optional business ID to filter data
            db: Database session
            
        Returns:
            List of top objections
        """
        # Build filters
        filters = [DetectedObjection.created_at.between(start_date, end_date)]
        
        if business_id is not None:
            filters.append(Lead.business_id == business_id)
        
        # Query for objections grouped by type
        objection_counts = db.query(
            DetectedObjection.objection_type, 
            func.count(DetectedObjection.id).label('count')
        ).join(
            Lead, DetectedObjection.lead_id == Lead.id
        ).filter(
            *filters
        ).group_by(
            DetectedObjection.objection_type
        ).order_by(
            desc('count')
        ).limit(3).all()
        
        # Format the results
        top_objections = []
        for objection_type, count in objection_counts:
            top_objections.append({
                "type": objection_type.value,
                "count": count
            })
        
        return top_objections
    
    @classmethod
    def _get_lead_details(
        cls,
        start_date: datetime,
        end_date: datetime,
        business_id: Optional[int],
        db: Session
    ) -> List[Dict[str, Any]]:
        """
        Get details for leads that were active during the report period.
        
        Args:
            start_date: Start date for the report period
            end_date: End date for the report period
            business_id: Optional business ID to filter data
            db: Database session
            
        Returns:
            List of lead details
        """
        # Build filters
        filters = [
            Lead.created_at.between(start_date, end_date) | 
            Lead.updated_at.between(start_date, end_date) |
            Lead.last_contact.between(start_date, end_date)
        ]
        
        if business_id is not None:
            filters.append(Lead.business_id == business_id)
        
        # Query for leads
        leads = db.query(Lead).filter(*filters).all()
        
        # Format the results
        lead_details = []
        for lead in leads:
            lead_details.append({
                "id": lead.id,
                "name": lead.full_name,
                "email": lead.email,
                "company": lead.company,
                "status": lead.status.value,
                "created_at": lead.created_at.isoformat() if lead.created_at else None,
                "last_contact": lead.last_contact.isoformat() if lead.last_contact else None
            })
        
        return lead_details
    
    @classmethod
    def _format_text_report(cls, report_data: Dict[str, Any]) -> str:
        """
        Format the report data as plain text.
        
        Args:
            report_data: The report data
            
        Returns:
            Formatted text report
        """
        metrics = report_data["metrics"]
        
        # Build the report text
        lines = [
            f"{'=' * 50}",
            f"AI SALES CLOSER ACTIVITY REPORT - {report_data['report_type'].upper()}",
            f"{'=' * 50}",
            f"Period: {report_data['start_date']} to {report_data['end_date']}",
            f"Generated: {report_data['generated_at']}",
            "",
            "SUMMARY METRICS:",
            f"- New Leads: {metrics['new_leads']}",
            f"- Meetings Scheduled: {metrics['meetings_scheduled']}",
            f"- Follow-ups Scheduled: {metrics['followups_scheduled']}",
            f"- Closed Sales: {metrics['closed_sales']}",
            f"- Total Conversations: {metrics['conversation_count']}",
            "",
            "LEADS BY STATUS:",
        ]
        
        # Add lead status breakdown
        for status, count in metrics['leads_by_status'].items():
            lines.append(f"- {status.title()}: {count}")
        
        lines.extend([
            "",
            "TOP OBJECTIONS:",
        ])
        
        # Add top objections
        if metrics['top_objections']:
            for i, objection in enumerate(metrics['top_objections'], 1):
                lines.append(f"{i}. {objection['type'].replace('_', ' ').title()}: {objection['count']} occurrences")
        else:
            lines.append("No objections recorded during this period.")
        
        # Add lead details if present
        if report_data.get("leads"):
            lines.extend([
                "",
                "ACTIVE LEADS:",
                "-" * 50,
            ])
            
            for lead in report_data["leads"]:
                lines.append(f"- {lead['name']} ({lead['email']}) - Status: {lead['status'].title()}")
        
        lines.extend([
            "",
            f"{'=' * 50}",
            "END OF REPORT",
            f"{'=' * 50}",
        ])
        
        return "\n".join(lines)
    
    @classmethod
    def _format_html_report(cls, report_data: Dict[str, Any]) -> str:
        """
        Format the report data as HTML.
        
        Args:
            report_data: The report data
            
        Returns:
            Formatted HTML report
        """
        metrics = report_data["metrics"]
        
        # Build the HTML report
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>AI Sales Closer Report - {report_data['report_type'].title()}</title>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; max-width: 800px; margin: 0 auto; padding: 20px; }}
                h1, h2, h3 {{ color: #2c3e50; }}
                .header {{ background-color: #3498db; color: white; padding: 10px; text-align: center; }}
                .section {{ margin-bottom: 20px; }}
                .metric {{ display: inline-block; background-color: #f8f9fa; border-radius: 5px; padding: 10px; margin: 10px; text-align: center; min-width: 150px; }}
                .metric-value {{ font-size: 24px; font-weight: bold; color: #3498db; }}
                .metric-label {{ font-size: 14px; color: #7f8c8d; }}
                table {{ width: 100%; border-collapse: collapse; margin-top: 10px; }}
                th, td {{ padding: 8px; text-align: left; border-bottom: 1px solid #ddd; }}
                th {{ background-color: #f2f2f2; }}
                tr:hover {{ background-color: #f5f5f5; }}
                .footer {{ margin-top: 30px; text-align: center; font-size: 12px; color: #7f8c8d; }}
            </style>
        </head>
        <body>
            <div class="header">
                <h1>AI Sales Closer Activity Report</h1>
                <p>{report_data['report_type'].title()} Report: {report_data['start_date']} to {report_data['end_date']}</p>
            </div>
            
            <div class="section">
                <h2>Summary Metrics</h2>
                <div class="metric">
                    <div class="metric-value">{metrics['new_leads']}</div>
                    <div class="metric-label">New Leads</div>
                </div>
                <div class="metric">
                    <div class="metric-value">{metrics['meetings_scheduled']}</div>
                    <div class="metric-label">Meetings Scheduled</div>
                </div>
                <div class="metric">
                    <div class="metric-value">{metrics['closed_sales']}</div>
                    <div class="metric-label">Closed Sales</div>
                </div>
                <div class="metric">
                    <div class="metric-value">{metrics['conversation_count']}</div>
                    <div class="metric-label">Conversations</div>
                </div>
            </div>
            
            <div class="section">
                <h2>Leads by Status</h2>
                <table>
                    <tr>
                        <th>Status</th>
                        <th>Count</th>
                    </tr>
        """
        
        # Add lead status rows
        for status, count in metrics['leads_by_status'].items():
            html += f"""
                    <tr>
                        <td>{status.title()}</td>
                        <td>{count}</td>
                    </tr>
            """
        
        html += """
                </table>
            </div>
            
            <div class="section">
                <h2>Top Objections</h2>
        """
        
        # Add top objections
        if metrics['top_objections']:
            html += """
                <table>
                    <tr>
                        <th>Objection Type</th>
                        <th>Count</th>
                    </tr>
            """
            
            for objection in metrics['top_objections']:
                html += f"""
                    <tr>
                        <td>{objection['type'].replace('_', ' ').title()}</td>
                        <td>{objection['count']}</td>
                    </tr>
                """
            
            html += """
                </table>
            """
        else:
            html += "<p>No objections recorded during this period.</p>"
        
        html += """
            </div>
        """
        
        # Add lead details if present
        if report_data.get("leads"):
            html += """
            <div class="section">
                <h2>Active Leads</h2>
                <table>
                    <tr>
                        <th>Name</th>
                        <th>Email</th>
                        <th>Company</th>
                        <th>Status</th>
                        <th>Last Contact</th>
                    </tr>
            """
            
            for lead in report_data["leads"]:
                html += f"""
                    <tr>
                        <td>{lead['name']}</td>
                        <td>{lead['email']}</td>
                        <td>{lead.get('company', 'N/A')}</td>
                        <td>{lead['status'].title()}</td>
                        <td>{lead.get('last_contact', 'Never')}</td>
                    </tr>
                """
            
            html += """
                </table>
            </div>
            """
        
        html += """
            <div class="footer">
                <p>Generated by AI Sales Closer at {}</p>
            </div>
        </body>
        </html>
        """.format(report_data['generated_at'])
        
        return html
    
    @classmethod
    def send_report_email(
        cls,
        report_data: Dict[str, Any],
        recipient_email: str,
        report_format: str = ReportFormat.HTML
    ) -> Dict[str, Any]:
        """
        Send the report via email.
        
        Args:
            report_data: The report data
            recipient_email: Email address to send the report to
            report_format: Format of the report (html or text)
            
        Returns:
            Result of the email sending operation
        """
        # Format the report
        if report_format == ReportFormat.HTML:
            report_content = cls._format_html_report(report_data)
            content_type = "html"
        else:
            report_content = cls._format_text_report(report_data)
            content_type = "text"
        
        # Build the email subject
        report_type = report_data['report_type'].title()
        report_date = datetime.fromisoformat(report_data['end_date']).strftime("%Y-%m-%d")
        subject = f"AI Sales Closer {report_type} Report - {report_date}"
        
        # Send the email
        return MessagingService.send_email(
            to_email=recipient_email,
            subject=subject,
            content=report_content,
            content_type=content_type
        )
    
    @classmethod
    def schedule_recurring_reports(
        cls,
        report_type: str,
        recipient_email: str,
        schedule_time: str,  # Format: "HH:MM"
        include_lead_details: bool = False,
        report_format: str = ReportFormat.HTML,
        business_id: Optional[int] = None,
        db: Session = None
    ) -> Dict[str, Any]:
        """
        Schedule recurring reports to be sent automatically.
        
        Args:
            report_type: Type of report (daily, weekly, monthly)
            recipient_email: Email address to send the report to
            schedule_time: Time of day to send the report (HH:MM)
            include_lead_details: Whether to include details for each lead
            report_format: Format of the report (html or text)
            business_id: Optional business ID to filter data
            db: Database session
            
        Returns:
            Dictionary with scheduling information
        """
        close_db = False
        if db is None:
            db = get_db_session()
            close_db = True
        
        try:
            # Validate report type
            if report_type not in [ReportType.DAILY, ReportType.WEEKLY, ReportType.MONTHLY]:
                return {
                    "success": False,
                    "error": f"Invalid report type: {report_type}"
                }
            
            # Validate schedule time format
            try:
                hours, minutes = map(int, schedule_time.split(":"))
                if hours < 0 or hours > 23 or minutes < 0 or minutes > 59:
                    raise ValueError()
            except ValueError:
                return {
                    "success": False,
                    "error": "Invalid schedule time format. Use HH:MM (24-hour format)"
                }
            
            # Create a scheduled task in the database
            # This is a placeholder - in a real implementation, you would add
            # a record to the database and have a scheduler service that checks
            # for tasks to run
            
            # For now, just return the configuration
            return {
                "success": True,
                "report_config": {
                    "report_type": report_type,
                    "recipient_email": recipient_email,
                    "schedule_time": schedule_time,
                    "include_lead_details": include_lead_details,
                    "report_format": report_format,
                    "business_id": business_id
                }
            }
        finally:
            if close_db:
                db.close() 