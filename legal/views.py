from django.shortcuts import render


def privacy_policy(request):
    return render(request, 'legal/privacy.html')


def terms_conditions(request):
    return render(request, 'legal/terms.html')

def about(request):
    return render(request, 'legal/about.html')


def home(request):
    return render(request, 'legal/home.html')


def faq(request):
    return render(request, 'legal/faq.html')


def contact(request):
    return render(request, 'legal/contact.html')

def support(request):
    return render(request, 'legal/support.html')